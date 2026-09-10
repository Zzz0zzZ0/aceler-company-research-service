"""Resume, stop, and write-scope checks without network or live CRM mutations."""
import copy
import fcntl
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "crm_enrichment.py"
SPEC = importlib.util.spec_from_file_location("crm_enrichment", SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
MANIFEST = {"industries": {"TAO_CI": "陶瓷", "QI_TA": "其他"}}
ROW = {"id": "test-company", "name": "Development Ceramics", "website": "https://example.test",
       "linkedin_url": None, "country": "UK", "background": "Existing verified information", "industry": None,
       "rating": "RATING_4", "updated_at": "earlier"}


def proposal(changes):
    return {"adapter_version": M.ADAPTER_VERSION, "id": ROW["id"], "updates": changes}


class EnrichmentTests(unittest.TestCase):
    def test_rating_boundaries_and_existing_values(self):
        for score, stars in [(0, 1), (19, 1), (20, 2), (39, 2), (40, 3), (60, 4), (79, 4), (80, 5), (100, 5)]:
            self.assertEqual(M.rating(score), f"RATING_{stars}")
        changes = M.updates(ROW, {"industry": "TAO_CI", "background_action": "keep"}, "New report", 90)
        self.assertEqual(changes, {"industry": "TAO_CI"})
        with self.assertRaises(ValueError):
            M.check_changes(ROW, {"rating": "RATING_5"}, MANIFEST)
        with self.assertRaises(ValueError):
            M.check_changes(ROW, {"source": "AGENT1"}, MANIFEST)

    def connection(self, current, returned=None):
        cursor = MagicMock()
        cursor.description = [SimpleNamespace(name=key) for key in current]
        cursor.fetchone.side_effect = [tuple(current.values()), returned]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection, cursor

    def test_crash_after_commit_does_not_write_again(self):
        current = {**ROW, "industry": "TAO_CI", "eligible": True}
        connection, cursor = self.connection(current)
        with tempfile.TemporaryDirectory() as temporary, patch.object(M, "crm_connection", return_value=connection), patch.dict(M.os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_test"}):
            run = Path(temporary)
            proposed = proposal({"industry": "TAO_CI"})
            audit = M.apply_one(ROW, 1, run, MANIFEST, proposed)
            self.assertEqual(audit["status"], "already_applied")
            self.assertEqual(cursor.execute.call_count, 2)  # timeout + read; no UPDATE
            with patch.object(M, "crm_connection", side_effect=AssertionError("second write")):
                self.assertEqual(M.apply_one(ROW, 1, run, MANIFEST, proposed), audit)

    def test_live_changes_and_ineligible_companies_are_not_overwritten(self):
        for changed, expected in [({"industry": "QI_TA"}, "conflict"), ({"eligible": False}, "no_longer_eligible"), ({"website": "https://new.test"}, "identity_changed")]:
            current = {**ROW, "eligible": True, **changed}
            connection, cursor = self.connection(current)
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary, patch.object(M, "crm_connection", return_value=connection), patch.dict(M.os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_test"}):
                audit = M.apply_one(ROW, 1, Path(temporary), MANIFEST, proposal({"industry": "TAO_CI"}))
                self.assertEqual(audit["status"], expected)
                self.assertEqual(cursor.execute.call_count, 2)

    def test_update_rechecks_contact_scope_and_checks_returned_fields(self):
        connection, cursor = self.connection({**ROW, "eligible": True}, (ROW["background"], "TAO_CI", ROW["rating"]))
        with tempfile.TemporaryDirectory() as temporary, patch.object(M, "crm_connection", return_value=connection), patch.dict(M.os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_test"}):
            audit = M.apply_one(ROW, 1, Path(temporary), MANIFEST, proposal({"industry": "TAO_CI"}))
        self.assertEqual(audit["status"], "applied")
        query, params = cursor.execute.call_args.args
        text = query.as_string()
        self.assertIn("NOT EXISTS", text)
        self.assertIn("'NO_REPLY','NEW'", text)
        self.assertNotIn('"background"=%s', text)
        self.assertNotIn('"rating"=%s', text)
        self.assertEqual(params, ("TAO_CI", ROW["id"]))

    def test_stop_drains_current_item_and_resume_skips_completed(self):
        rows = [{**ROW, "id": str(index)} for index in range(3)]
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            def fake_prepare(row, index, run, manifest):
                calls.append(row["id"])
                proposal = {"status": "ready", "updates": {}, "adapter_version": M.ADAPTER_VERSION}
                M.save(run / "records" / f"{index:03d}-{row['id']}" / "proposal.json", proposal)
                if len(calls) == 1:
                    (run / "STOP").touch()
                return proposal
            with patch.object(M, "prepare", side_effect=fake_prepare):
                M.run_queue(run, MANIFEST, rows, 1, 0, False, False)
                self.assertEqual(calls, ["0"])
                self.assertEqual(M.read(run / "progress.json")["status"], "paused")
                (run / "STOP").unlink()
                M.run_queue(run, MANIFEST, rows, 1, 0, False, False)
            self.assertEqual(calls, ["0", "1", "2"])
            self.assertEqual(M.read(run / "progress.json")["counts"], {"ready": 3})

    def test_advisory_lock_detects_live_worker_and_releases_on_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with (run / "run.lock").open("a") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                self.assertTrue(M.locked(run))
            self.assertFalse(M.locked(run))

    def test_background_append_cannot_delete_existing_product_details(self):
        with self.assertRaises(ValueError):
            M.check_changes(ROW, {"background": "A shorter summary"}, MANIFEST)
        M.check_changes(ROW, {"background": ROW["background"] + "\n\n补充背调（2026-09-10）：\nNew verified fact"}, MANIFEST)

    def test_adapter_upgrade_reuses_research_checkpoint(self):
        item = {"status": "valid", "assessment": {"identity_status": "confirmed", "sources": [{"id": "S1", "url": "https://example.test", "title": "Official"}]},
                "translation": {"status": "not_needed"}, "validation": {"score": 80}}
        decision = {"industry": "TAO_CI", "industry_reason": "已确认陶瓷主营业务", "evidence_ids": ["S1"],
                    "background_action": "keep", "background_summary": "", "background_evidence_ids": [], "background_reason": "旧信息完整"}
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            directory = run / "records" / f"001-{ROW['id']}"
            M.save(directory / "result.json", item)
            M.save(directory / "proposal.json", {"status": "ready", "adapter_version": M.ADAPTER_VERSION-1})
            with patch.object(M, "research_one", side_effect=AssertionError("must reuse research")), patch.object(M, "_invoke_hermes", return_value={"assessment": decision}) as adapter:
                result = M.prepare(ROW, 1, run, MANIFEST)
            adapter.assert_called_once()
            self.assertEqual(result["updates"], {"industry": "TAO_CI"})
            self.assertEqual(result["adapter_version"], M.ADAPTER_VERSION)

    def test_status_identifies_interrupted_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            M.save(run / "progress.json", {"status": "running", "completed": 2})
            self.assertEqual(M.status(run)["state"], "interrupted")

    def test_failed_company_is_retryable_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            directory = run / "records" / f"001-{ROW['id']}"
            M.save(directory / "proposal.json", {"status": "failed"})
            M.save(directory / "result.json", {"status": "failed", "errors": ["previous outage"]})
            with patch.object(M, "research_one", return_value={"status": "failed", "errors": ["still unavailable"]}) as research:
                result = M.prepare(ROW, 1, run, MANIFEST)
            research.assert_called_once()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(list((directory / "previous-failures").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
