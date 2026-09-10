"""Resume, stop, and write-scope checks without network or live CRM mutations."""
import copy
import fcntl
import importlib.util
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from company_research_trial import company_research_trial as C

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
    def test_key_interface_blocks_cross_origin_and_never_echoes_key(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(M, "target", return_value="test-db"):
            run = Path(temporary); M.save(run / "manifest.json", {"target": "test-db"})
            with M.key_ui_server(run, {}) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                base = f"http://127.0.0.1:{server.server_port}"
                def request(origin, payload):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request("POST", "/key-and-resume", json.dumps(payload), {"Content-Type": "application/json", "Origin": origin})
                    response = connection.getresponse(); result = (response.status, response.read().decode()); connection.close(); return result
                try:
                    with patch.object(M, "start", return_value={"running": True}) as start:
                        self.assertEqual(request("https://untrusted.test", {"api_key": "test-key-value"})[0], 403)
                        start.assert_not_called()
                        self.assertEqual(request(base, {"api_key": "bad"})[0], 400)
                        start.assert_not_called()
                        code, body = request(base, {"api_key": "test-key-value"})
                        self.assertEqual(code, 200); self.assertNotIn("test-key-value", body)
                        start.assert_called_once_with(run, {}, anysearch_key="test-key-value")
                finally:
                    server.shutdown(); thread.join()

    def test_new_key_is_persisted_and_used_for_restart_without_secret_audit(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(M.os.environ, {"ANYSEARCH_API_KEY": "old-test-key"}):
            run = Path(temporary); env = run / "test.env"; env.write_text("ANYSEARCH_API_KEY=old-test-key\nOTHER=preserved\n")
            settings = {"crm_env": "/test/crm.env", "workers": 5, "limit": 0, "apply": True}
            process = MagicMock(); process.poll.return_value = 0
            seen_keys = []
            def launch(*args, **kwargs):
                seen_keys.append(M.os.environ["ANYSEARCH_API_KEY"])
                self.assertNotIn("new-test-key", str(args))
                return process
            with patch.object(M, "DEFAULT_ENV_FILE", env), patch.object(M.subprocess, "Popen", side_effect=launch):
                M.start(run, settings, anysearch_key="new-test-key")
            self.assertEqual(M._read_anysearch_key(env), "new-test-key")
            self.assertIn("OTHER=preserved", env.read_text())
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(seen_keys, ["new-test-key"])
            self.assertNotIn("new-test-key", (run / "key-update.json").read_text())
            with patch.object(M, "locked", return_value=True), patch.object(M, "_write_anysearch_key") as write:
                with self.assertRaises(ValueError):
                    M.start(run, settings, anysearch_key="another-test-key")
                write.assert_not_called()

    def low_item(self, score=0):
        return {"status": "valid", "record": ROW.copy(), "assessment": {"identity_status": "confirmed"},
                "validation": {"valid": True, "score": score}}

    def test_low_fit_requires_success_identity_and_strict_score_boundary(self):
        self.assertTrue(M.low_fit(self.low_item(0)))
        self.assertTrue(M.low_fit(self.low_item(19)))
        self.assertFalse(M.low_fit(self.low_item(20)))
        for change in ({"status": "failed"}, {"validation": {"valid": False, "score": 0}},
                       {"assessment": {"identity_status": "unresolved"}},
                       {"validation": {"valid": True, "score": None}}):
            self.assertFalse(M.low_fit({**self.low_item(), **change}))

    def test_low_fit_skips_translation_and_field_model(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(M, "research_one", return_value=self.low_item()), patch.object(M, "localize_item") as translate, patch.object(M, "_invoke_hermes") as model:
            result = M.prepare(ROW, 1, Path(temporary), MANIFEST)
        self.assertEqual(result["status"], "low_fit")
        translate.assert_not_called()
        model.assert_not_called()

    def test_soft_delete_and_commit_before_receipt_recovery(self):
        current = {**ROW, "deleted_at": None, "eligible": True}
        timestamp = "2026-09-10 03:00:00+00"
        connection, cursor = self.connection(current)
        cursor.fetchone.side_effect = [tuple(current.values()), (timestamp,), (timestamp,)]
        with tempfile.TemporaryDirectory() as temporary, patch.dict(M.os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_test"}):
            run = Path(temporary); directory = run / "records" / f"001-{ROW['id']}"
            M.save(directory / "result.json", self.low_item())
            with patch.object(M, "crm_connection", return_value=connection):
                result = M.delete_low_fit(ROW, 1, run)
            self.assertEqual(result["status"], "deleted_low_fit")
            query, params = cursor.execute.call_args.args
            self.assertIn('SET "deletedAt"=', query.as_string())
            self.assertIn("NOT EXISTS", query.as_string())
            self.assertNotIn("DELETE FROM", query.as_string())
            self.assertEqual(params, (timestamp, ROW["id"]))
            (directory / "deletion.json").unlink()  # DB committed; receipt lost
            recovered, cur = self.connection({**current, "deleted_at": timestamp, "eligible": False})
            with patch.object(M, "crm_connection", return_value=recovered):
                self.assertEqual(M.delete_low_fit(ROW, 1, run)["status"], "already_deleted_low_fit")
            self.assertEqual(cur.execute.call_count, 2)
            with patch.object(M, "crm_connection", side_effect=AssertionError("repeated deletion")):
                self.assertEqual(M.delete_low_fit(ROW, 1, run)["status"], "already_deleted_low_fit")

    def test_deletion_preserves_failed_research_and_live_changes(self):
        for change, expected in [({"industry": "QI_TA"}, "deletion_conflict"),
                                 ({"eligible": False}, "deletion_scope_changed"),
                                 ({"name": "Renamed"}, "deletion_identity_changed")]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary, patch.dict(M.os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_test"}):
                run = Path(temporary); directory = run / "records" / f"001-{ROW['id']}"
                M.save(directory / "result.json", self.low_item())
                con, cur = self.connection({**ROW, "deleted_at": None, "eligible": True, **change})
                with patch.object(M, "crm_connection", return_value=con):
                    self.assertEqual(M.delete_low_fit(ROW, 1, run)["status"], expected)
                self.assertEqual(cur.execute.call_count, 2)
        with tempfile.TemporaryDirectory() as temporary, patch.object(M, "crm_connection") as db:
            run = Path(temporary)
            M.save(run / "records" / f"001-{ROW['id']}" / "result.json", {**self.low_item(), "status": "failed"})
            with self.assertRaises(ValueError):
                M.delete_low_fit(ROW, 1, run)
            db.assert_not_called()

    def test_previously_enriched_low_fit_is_processed_for_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary); directory = run / "records" / f"001-{ROW['id']}"
            M.save(directory / "result.json", self.low_item())
            M.save(directory / "apply.json", {"status": "applied"})
            with patch.object(M, "delete_low_fit", return_value={"status": "deleted_low_fit"}) as delete, patch.object(M, "prepare") as prepare:
                M.run_queue(run, MANIFEST, [ROW], 1, 0, True, False)
            delete.assert_called_once()
            prepare.assert_not_called()
            self.assertEqual(M.read(run / "progress.json")["counts"], {"deleted_low_fit": 1})

    def test_quota_detection_distinguishes_limits_and_page_content(self):
        for message in ("API Error: You've reached your API key's total free quota for today.",
                        "API Error: You've reached your API key's total quota.",
                        "API Error: insufficient_quota", "API Error: Insufficient balance",
                        "API Error: credits exhausted", "API Error: 额度已耗尽"):
            self.assertTrue(C.anysearch_quota_exhausted(SimpleNamespace(returncode=1, stderr=message, stdout="")))
        self.assertTrue(C.anysearch_quota_exhausted(SimpleNamespace(returncode=0, stderr="", stdout="Search failed: quota exceeded")))
        self.assertFalse(C.anysearch_quota_exhausted(SimpleNamespace(returncode=1, stderr="HTTP 429 Too many requests", stdout="")))
        self.assertFalse(C.anysearch_quota_exhausted(SimpleNamespace(returncode=0, stderr="", stdout="# A page about insufficient quota")))

    def test_quota_propagates_without_fallback_pauses_and_notifies_once(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(C.os.environ, {"ANYSEARCH_STOP_ON_QUOTA": "1"}), patch.object(C, "_ANYSEARCH_QUOTA_EXHAUSTED", C.threading.Event()), patch.object(C, "_public_web_fallback") as fallback, patch.object(C, "_invoke_hermes") as model, patch.object(M, "notify_quota_pause", return_value={"status": "submitted"}) as notify:
            run = Path(temporary); cli = run / "cli.js"; cli.touch()
            response = SimpleNamespace(returncode=1, stderr="API Error: insufficient credits", stdout="")
            with patch.object(C, "ANYSEARCH_CLI", cli), patch.object(C, "ANYSEARCH_CACHE_DIR", run / "cache"), patch.object(C.subprocess, "run", return_value=response) as call:
                M.run_queue(run, MANIFEST, [ROW, {**ROW, "id": "second"}], 1, 0, True, False)
                self.assertEqual(call.call_count, 1)
                with self.assertRaises(C.AnySearchQuotaExhausted):
                    C.run_anysearch_cli(["extract", "https://example.test"])
                self.assertEqual(call.call_count, 1)
            fallback.assert_not_called(); model.assert_not_called(); notify.assert_called_once()
            self.assertEqual(M.read(run / "progress.json")["status"], "paused")
            self.assertEqual(M.read(run / "progress.json")["completed"], 1)
            self.assertEqual(M.status(run)["alert"]["reason"], "anysearch_quota_exhausted")
            self.assertFalse((run / "records" / f"001-{ROW['id']}" / "apply.json").exists())
            (run / "STOP").unlink()
            with patch.object(M, "prepare", return_value={"status": "review"}) as resumed:
                M.run_queue(run, MANIFEST, [ROW, {**ROW, "id": "second"}], 1, 0, False, False)
            self.assertEqual(resumed.call_count, 2)

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
