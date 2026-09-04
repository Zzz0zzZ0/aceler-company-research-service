from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from company_research_trial.dashboard import DEFAULT_HOST, DEFAULT_PORT, HTML, DashboardData, make_server


def _assessment(name: str = "Example Steel") -> dict:
    return {
        "company": name,
        "company_positioning": {"text": "Official EAF steel producer.", "evidence_ids": ["S1"]},
        "role_judgment": {
            "operational_role": "终端用户",
            "commercial_relationship": "潜在客户",
            "reason": "The process page confirms EAF production.",
            "evidence_ids": ["S1"],
        },
        "match": {
            "product_match": 9,
            "commercial_match": 8,
            "follow_up": "跟进",
            "decision_rationale": "Confirmed recurring EAF demand supports follow-up.",
            "confidence": "中",
            "entry_barrier": "高",
            "rationale": "Process and catalog fit are confirmed.",
            "components": {
                "production_process_need": 28,
                "catalog_fit": 26,
                "consumption_intensity": 17,
                "demand_recurrence": 9,
                "company_role_fit": 8,
            },
        },
        "confirmed_processes": ["EAF"],
        "procurement_directions": [
            {
                "product": "Graphite Electrode",
                "priority": "高",
                "application": "EAF steelmaking",
                "basis": "Official process page",
                "evidence_status": "推测",
                "next_question": "Confirm grade.",
            }
        ],
        "sources": [
            {
                "id": "S1",
                "title": "Official process page",
                "url": "https://example.test/process",
                "source_type": "官网",
            }
        ],
    }


def _record(index: int, *, status: str = "valid", assessment: dict | None = None) -> dict:
    item = {
        "index": index,
        "record": {
            "id": f"company-{index}",
            "name": "Example Steel" if index == 1 else f"Example {index}",
            "website": "https://example.test",
            "linkedin_url": "https://www.linkedin.com/company/example",
            "industry": "GANG_TIE_YE_JIN",
            "background": "CRM background kept for comparison.",
            "updated_at": "2026-08-18T00:00:00Z",
            "contact_count": 3,
            "weakness_reasons": ["背景较短"],
        },
        "status": status,
        "assessment": assessment,
        "validation": {
            "valid": status == "valid",
            "score": 88,
            "level": "高",
            "product_match": 9,
            "commercial_match": 8,
            "follow_up": "跟进",
        }
        if status == "valid"
        else {"valid": False, "errors": ["Hermes timed out"]},
        "errors": [] if status == "valid" else ["Hermes timed out"],
        "duration_seconds": 12.5,
        "usage": {"total_tokens": 12345, "secret": "must not be exposed"},
    }
    if status == "deferred":
        item["defer_reason"] = "deferred_timeout"
    return item


class DashboardDataTests(unittest.TestCase):
    def test_default_server_is_exposed_on_fixed_lan_port(self) -> None:
        self.assertEqual(DEFAULT_HOST, "0.0.0.0")
        self.assertEqual(DEFAULT_PORT, 8766)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._make_run("20260817T000000Z", [_record(2, assessment=_assessment("Example 2"))])
        self._make_run(
            "20260818T000000Z",
            [_record(1, status="deferred", assessment=None), _record(2, assessment=_assessment())],
        )
        (self.root / "not-a-run.txt").write_text("ignored", encoding="utf-8")
        self.data = DashboardData(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_run(self, run_id: str, records: list[dict]) -> None:
        run = self.root / run_id
        records_root = run / "records"
        records_root.mkdir(parents=True)
        (run / "summary.json").write_text(
            json.dumps({"selected": len(records), "valid": 1, "deferred": 1, "failed": 0}),
            encoding="utf-8",
        )
        for item in records:
            record_dir = records_root / f"{item['index']:03d}-abc"
            record_dir.mkdir()
            (record_dir / "result.json").write_text(json.dumps(item), encoding="utf-8")

    def test_runs_are_sorted_newest_first_and_statuses_are_scanned(self) -> None:
        runs = self.data.runs()
        self.assertEqual([item["run_id"] for item in runs], ["20260818T000000Z", "20260817T000000Z"])
        self.assertEqual(runs[0]["stats"]["selected"], 2)
        self.assertEqual(runs[0]["stats"]["failed"], 1)
        self.assertNotIn("deferred", runs[0]["stats"])
        self.assertEqual(runs[0]["stats"]["valid"], 1)

    def test_run_id_traversal_is_rejected(self) -> None:
        for run_id in ("../20260817T000000Z", "20260817T000000Z/../x", "..", ""):
            with self.subTest(run_id=run_id):
                with self.assertRaises(ValueError):
                    self.data.run(run_id)

    def test_dashboard_prefers_the_localized_display_copy(self) -> None:
        result_path = self.root / "20260818T000000Z" / "records" / "002-abc" / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        localized = json.loads(json.dumps(result["assessment"]))
        localized["company_positioning"]["text"] = "中文展示文本"
        result["display_assessment"] = localized
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        payload = self.data.run("20260818T000000Z")
        company = next(item for item in payload["companies"] if item["record_id"] == "company-2")
        self.assertEqual(company["assessment"]["company_positioning"]["text"], "中文展示文本")

    def test_assessment_null_is_friendly_and_crm_record_remains(self) -> None:
        payload = self.data.run("20260818T000000Z")
        failed = next(item for item in payload["companies"] if item["status"] == "failed")
        self.assertIsNone(failed["assessment"])
        self.assertEqual(failed["crm_record"]["name"], "Example Steel")
        self.assertEqual(failed["level"], "未评分")
        self.assertIn("deferred_timeout", failed["errors"])
        self.assertNotIn("defer_reason", failed)

    def test_html_exposes_only_valid_and_failed_controls(self) -> None:
        self.assertNotIn("已延后", HTML)
        self.assertNotIn('value="deferred"', HTML)

    def test_v2_result_uses_validator_score_without_recalculation(self) -> None:
        payload = self.data.run("20260817T000000Z")
        company = payload["companies"][0]
        self.assertEqual(company["score"], 88)
        self.assertEqual(company["level"], "高")
        self.assertEqual(company["assessment"]["match"]["components"]["catalog_fit"], 26)
        self.assertEqual(company["product_match"], 9)
        self.assertEqual(company["commercial_match"], 8)
        self.assertEqual(company["follow_up"], "跟进")
        self.assertIn("产品匹配", HTML)
        self.assertIn("商业匹配", HTML)
        self.assertIn("最终建议", HTML)
        self.assertEqual(company["assessment"]["procurement_directions"][0]["product"], "Graphite Electrode")
        self.assertNotIn("usage", json.dumps(payload, ensure_ascii=False))

    def test_missing_score_is_not_derived(self) -> None:
        run = self.root / "20260819T000000Z"
        record_dir = run / "records" / "001-abc"
        record_dir.mkdir(parents=True)
        item = _record(1, assessment=_assessment())
        item["validation"] = {"valid": True}
        (run / "summary.json").write_text("{}", encoding="utf-8")
        (record_dir / "result.json").write_text(json.dumps(item), encoding="utf-8")
        company = self.data.run("20260819T000000Z")["companies"][0]
        self.assertIsNone(company["score"])
        self.assertEqual(company["level"], "未评分")


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "outputs"
        run = root / "20260818T000000Z" / "records" / "001-abc"
        run.mkdir(parents=True)
        (root / "20260818T000000Z" / "summary.json").write_text("{}", encoding="utf-8")
        (run / "result.json").write_text(
            json.dumps(_record(1, assessment=None)), encoding="utf-8"
        )
        self.previous_anysearch_key = os.environ.get("ANYSEARCH_API_KEY")
        self.env_file = Path(self.temp.name) / "local.env"
        self.env_file.write_text("OTHER_SETTING=preserved\nANYSEARCH_API_KEY=old-test-key-1234\n", encoding="utf-8")
        self.server = make_server("127.0.0.1", 0, root, anysearch_env_file=self.env_file)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.previous_anysearch_key is None:
            os.environ.pop("ANYSEARCH_API_KEY", None)
        else:
            os.environ["ANYSEARCH_API_KEY"] = self.previous_anysearch_key
        self.temp.cleanup()

    def _post(self, path: str, body: object, content_type: str = "application/json") -> tuple[int, dict]:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def _fake_result(self, command: list[str], *, run_id: str = "20260819T010000Z", returncode: int = 1) -> subprocess.CompletedProcess:
        selected_file = Path(command[command.index("--selected-file") + 1])
        selected = json.loads(selected_file.read_text(encoding="utf-8"))
        run_dir = Path(command[command.index("--output-root") + 1]) / run_id
        record = _record(1, status="failed", assessment=None)
        record["record"].update(selected[0])
        record_dir = run_dir / "records" / "001-manual"
        record_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(
            json.dumps({"selected": 1, "valid": 0, "failed": 1}), encoding="utf-8"
        )
        (record_dir / "result.json").write_text(json.dumps(record), encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=json.dumps({"run_dir": str(run_dir)}, ensure_ascii=False) + "\n",
            stderr="MINIMAX_API_KEY=must-not-be-returned",
        )

    def test_core_api_and_http_errors(self) -> None:
        with urlopen(self.base + "/api/runs") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(len(json.load(response)["runs"]), 1)
        with urlopen(self.base + "/api/runs/20260818T000000Z") as response:
            payload = json.load(response)
            self.assertEqual(payload["companies"][0]["assessment"], None)
        with self.assertRaises(HTTPError) as missing:
            urlopen(self.base + "/api/runs/../secret")
        self.assertEqual(missing.exception.code, 404)
        for method_name in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
            with self.subTest(method=method_name):
                with self.assertRaises(HTTPError) as method:
                    urlopen(Request(self.base + "/api/runs", method=method_name))
                self.assertEqual(method.exception.code, 405)

    def test_manual_research_uses_injected_runner_and_returns_failed_run(self) -> None:
        calls: list[list[str]] = []

        def fake_runner(command: list[str]) -> subprocess.CompletedProcess:
            calls.append(command)
            return self._fake_result(command)

        self.server.research_runner = fake_runner
        status, payload = self._post(
            "/api/research",
            {
                "name": "Manual Steel",
                "website": "example.test",
                "linkedin_url": "https://www.linkedin.com/company/manual-steel",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["exit_code"], 1)
        self.assertEqual(payload["run_id"], "20260819T010000Z")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "-m")
        selected_file = Path(calls[0][calls[0].index("--selected-file") + 1])
        self.assertFalse(selected_file.exists())
        with urlopen(self.base + "/api/runs/20260819T010000Z") as response:
            result = json.load(response)
        self.assertEqual(result["companies"][0]["name"], "Manual Steel")
        self.assertEqual(result["companies"][0]["status"], "failed")

    def test_manual_research_rejects_bad_json_content_type_and_size(self) -> None:
        status, payload = self._post("/api/research", b"{}", "text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(payload["error"], "unsupported_media_type")
        status, payload = self._post("/api/research", b"not-json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_json")
        status, payload = self._post("/api/research", {"name": "  "})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_name")
        status, payload = self._post("/api/research", {"name": "A", "extra": "no"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "unexpected_fields")
        status, payload = self._post("/api/research", b"x" * (16 * 1024 + 1))
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "request_too_large")

    def test_anysearch_key_endpoint_masks_and_atomically_updates_local_env(self) -> None:
        with urlopen(self.base + "/api/settings/anysearch") as response:
            initial = json.load(response)
        self.assertEqual(initial, {"configured": True, "masked": "••••1234"})

        new_key = "new-test-key-9876"
        status, payload = self._post("/api/settings/anysearch", {"api_key": new_key})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"configured": True, "masked": "••••9876", "updated": True})
        self.assertNotIn(new_key, json.dumps(payload))
        self.assertIn("OTHER_SETTING=preserved", self.env_file.read_text(encoding="utf-8"))
        self.assertIn("ANYSEARCH_API_KEY=new-test-key-9876", self.env_file.read_text(encoding="utf-8"))
        self.assertEqual(os.environ["ANYSEARCH_API_KEY"], new_key)

        status, payload = self._post("/api/settings/anysearch", {"api_key": "short"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_api_key")

    def test_manual_research_allows_only_one_in_flight(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocking_runner(command: list[str]) -> subprocess.CompletedProcess:
            started.set()
            release.wait(timeout=2)
            return self._fake_result(command, run_id="20260819T020000Z", returncode=0)

        self.server.research_runner = blocking_runner
        first: dict[str, object] = {}

        def submit_first() -> None:
            first["result"] = self._post("/api/research", {"name": "First Steel"})

        worker = threading.Thread(target=submit_first)
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        status, payload = self._post("/api/research", {"name": "Second Steel"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "research_in_progress")
        release.set()
        worker.join(timeout=3)
        self.assertEqual(first["result"], (200, {"run_id": "20260819T020000Z", "status": "completed", "exit_code": 0}))

    def test_html_has_manual_research_form_and_refresh(self) -> None:
        self.assertIn('id="research-open"', HTML)
        self.assertIn('id="research-drawer"', HTML)
        self.assertIn('id="research-close"', HTML)
        self.assertIn('role="dialog"', HTML)
        self.assertIn('aria-modal="true"', HTML)
        self.assertIn("containDrawerFocus", HTML)
        self.assertIn("$('app-shell').inert = true", HTML)
        self.assertIn('id="research-form"', HTML)
        self.assertIn('id="research-name"', HTML)
        self.assertIn('id="research-website"', HTML)
        self.assertIn('id="research-linkedin"', HTML)
        self.assertIn("/api/research", HTML)
        self.assertIn("loadRun(body.run_id)", HTML)
        self.assertIn("openResearch", HTML)
        self.assertIn("closeResearch", HTML)



if __name__ == "__main__":
    unittest.main()
