from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from company_research_trial import research_api as api


def valid_assessment() -> dict:
    return {
        "company_positioning": {"text": "Official manufacturer", "evidence_ids": []},
        "role_judgment": {"operational_role": "终端用户", "commercial_relationship": "潜在客户"},
        "match": {"confidence": "中", "entry_barrier": "中"},
        "procurement_directions": [],
    }


class ApiTests(unittest.TestCase):
    def runtime_patches(self, directory: str):
        root = Path(directory)
        skill = root / "skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("skill", encoding="utf-8")
        validator = root / "validate_assessment.py"
        validator.write_text("validator", encoding="utf-8")
        hermes = root / "hermes"
        hermes.write_text("#!/bin/sh\n", encoding="utf-8")
        hermes.chmod(0o755)
        return (
            patch.object(api, "HERMES_SKILL_DIR", skill),
            patch.object(api, "resolved_validator", return_value=validator),
            patch.object(api, "load_env_file"),
            hermes,
        )

    def test_python_interface_is_crm_free_and_writes_selection_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            patches = self.runtime_patches(directory)
            for item in patches[:3]:
                item.start()
            try:
                output_root = Path(directory) / "runs"
                captured: dict[str, object] = {}
                item = {
                    "status": "valid",
                    "record": {"id": "input-001", "name": "Example"},
                    "assessment": valid_assessment(),
                    "validation": {"valid": True, "score": 20, "level": "低", "errors": [], "warnings": []},
                    "usage": {"total_tokens": 1},
                    "errors": [],
                    "duration_seconds": 0.2,
                }

                def fake_research(record, **kwargs):
                    captured["record"] = record
                    captured["kwargs"] = kwargs
                    return item

                def fake_reports(run_dir, items):
                    captured["reports"] = (run_dir, items)

                with patch.object(api, "research_one", side_effect=fake_research) as research, patch.object(
                    api, "write_reports", side_effect=fake_reports
                ), patch.object(api, "render_assessment", return_value="# report"), patch(
                    "company_research_trial.company_research_trial.crm_connection", side_effect=AssertionError("CRM called")
                ):
                    result = api.research_company(
                        {"name": "  Example  ", "website": "https://example.test", "linkedin_url": ""},
                        output_root=output_root,
                        env_file=Path(directory) / "local.env",
                        hermes=patches[3],
                        timeout=12,
                        reasoning="low",
                        max_attempts=2,
                        review_zero_score=False,
                    )
                self.assertEqual(set(result), set(api.RESULT_FIELDS))
                self.assertEqual(result["status"], "valid")
                self.assertEqual(result["report_markdown"], "# report")
                research.assert_called_once()
                self.assertEqual(captured["record"]["name"], "Example")
                self.assertEqual(captured["record"]["website"], "https://example.test")
                self.assertEqual(captured["kwargs"]["index"], 1)
                self.assertEqual(captured["kwargs"]["timeout"], 12)
                self.assertEqual(captured["kwargs"]["reasoning"], "low")
                self.assertEqual(captured["kwargs"]["max_attempts"], 2)
                self.assertFalse(captured["kwargs"]["review_zero_score"])
                run_dir = output_root / result["trace_id"]
                self.assertEqual(json.loads((run_dir / "selected-companies.json").read_text()), [{"id": "input-001", "name": "Example", "website": "https://example.test"}])
                self.assertEqual(json.loads((run_dir / "summary.json").read_text())["valid"], 1)
            finally:
                for item in reversed(patches[:3]):
                    item.stop()

    def test_python_interface_accepts_name_only_without_crm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            patches = self.runtime_patches(directory)
            for item in patches[:3]:
                item.start()
            try:
                output_root = Path(directory) / "runs"
                captured: dict[str, object] = {}
                item = {
                    "status": "valid",
                    "record": {"id": "input-001", "name": "Example"},
                    "assessment": valid_assessment(),
                    "validation": {"valid": True, "score": 20, "level": "低", "errors": [], "warnings": []},
                    "usage": {"total_tokens": 1},
                    "errors": [],
                    "duration_seconds": 0.2,
                }

                def fake_research(record, **kwargs):
                    captured["record"] = record
                    return item

                with patch.object(api, "research_one", side_effect=fake_research) as research, patch.object(
                    api, "write_reports"
                ), patch.object(api, "render_assessment", return_value="# report"), patch(
                    "company_research_trial.company_research_trial.crm_connection", side_effect=AssertionError("CRM called")
                ):
                    result = api.research_company(
                        {"name": "  Example  "},
                        output_root=output_root,
                        env_file=Path(directory) / "local.env",
                        hermes=patches[3],
                        timeout=12,
                        reasoning="low",
                        max_attempts=2,
                        review_zero_score=False,
                    )
                self.assertEqual(result["status"], "valid")
                research.assert_called_once()
                self.assertEqual(captured["record"], {"id": "input-001", "name": "Example"})
                run_dir = output_root / result["trace_id"]
                self.assertEqual(
                    json.loads((run_dir / "selected-companies.json").read_text()),
                    [{"id": "input-001", "name": "Example"}],
                )
            finally:
                for item in reversed(patches[:3]):
                    item.stop()

    def test_request_rejection_happens_before_run_creation(self) -> None:
        cases = (
            {"name": "Example", "extra": 1},
            {"name": "   "},
            {"name": "Example", "website": "ftp://example.test"},
            {"name": "Example", "website": "https://"},
        )
        for request in cases:
            with self.subTest(request=request), tempfile.TemporaryDirectory() as directory:
                output_root = Path(directory) / "runs"
                with self.assertRaises(ValueError):
                    api.research_company(request, output_root=output_root)
                self.assertFalse(output_root.exists())

    def test_failed_research_returns_stable_failed_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            patches = self.runtime_patches(directory)
            for item in patches[:3]:
                item.start()
            try:
                failed = {
                    "status": "failed",
                    "record": {"id": "input-001", "name": "Broken"},
                    "assessment": None,
                    "validation": {"valid": False, "score": 0, "level": "低", "errors": ["bad output"], "warnings": []},
                    "usage": None,
                    "errors": ["bad output"],
                    "duration_seconds": 0,
                }
                with patch.object(api, "research_one", return_value=failed), patch.object(api, "write_reports"):
                    result = api.research_company(
                        {"name": "Broken"},
                        output_root=Path(directory) / "runs",
                        env_file=Path(directory) / "local.env",
                        hermes=patches[3],
                    )
                self.assertEqual(set(result), set(api.RESULT_FIELDS))
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["assessment"])
                self.assertEqual(result["report_markdown"], "")
                self.assertEqual(result["errors"], ["bad output"])
                self.assertEqual(json.loads((Path(directory) / "runs" / result["trace_id"] / "summary.json").read_text())["failed"], 1)
            finally:
                for item in reversed(patches[:3]):
                    item.stop()


class CliTests(unittest.TestCase):
    def run_cli(self, stdin: str, result: dict | None = None) -> tuple[int, dict]:
        output = io.StringIO()
        patcher = patch.object(api, "research_company", return_value=result) if result is not None else patch.object(api, "research_company")
        with patcher, patch.object(api.sys, "stdin", io.StringIO(stdin)), redirect_stdout(output):
            code = api.main([])
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])

    def test_cli_valid_failed_and_invalid_json_contract(self) -> None:
        valid = api._error_response([])
        valid.update({"status": "valid", "assessment": {}, "validation": {"valid": True}, "report_markdown": "ok"})
        code, result = self.run_cli('{"name":"Example"}', valid)
        self.assertEqual(code, 0)
        self.assertEqual(set(result), set(api.RESULT_FIELDS))

        failed = api._error_response(["bad"])
        code, result = self.run_cli('{"name":"Example"}', failed)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "failed")

        code, result = self.run_cli("not json")
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(set(result), set(api.RESULT_FIELDS))


if __name__ == "__main__":
    unittest.main()
