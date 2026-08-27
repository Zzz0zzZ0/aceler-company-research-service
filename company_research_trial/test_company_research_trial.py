from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from company_research_trial.company_research_trial import (
    DEFAULT_HERMES,
    DEFAULT_TOOLSETS,
    PROJECT_DIR,
    anysearch_pack,
    anysearch_source_errors,
    child_environment,
    extract_json_object,
    localize_item,
    main,
    read_candidates,
    research_one,
    research_prompt,
    zero_score_review_prompt,
    run_anysearch_cli,
    _identity_seed_name,
    _run_id,
    _search_result_urls,
    _substantive_extract,
    validate_assessment,
    validate_selected_records,
    write_reports,
)


VALIDATOR = PROJECT_DIR / "skill" / "aceler-company-research" / "scripts" / "validate_assessment.py"
REPORT_CONTRACT = PROJECT_DIR / "skill" / "aceler-company-research" / "references" / "report-contract.md"
PRODUCT_CONTRACT = PROJECT_DIR / "skill" / "aceler-company-research" / "references" / "aceler-products.md"


def assessment() -> dict:
    return {
        "company": "Example Steel",
        "identity_status": "confirmed",
        "research_status": "complete",
        "company_positioning": {"text": "Official EAF steel producer.", "evidence_ids": ["S1"]},
        "role_judgment": {
            "operational_role": "终端用户",
            "commercial_relationship": "潜在客户",
            "secondary_relationship": "",
            "reason": "The official process page confirms EAF production.",
            "evidence_ids": ["S1"],
        },
        "match": {
            "components": {
                "production_process_need": 28,
                "catalog_fit": 26,
                "consumption_intensity": 17,
                "demand_recurrence": 9,
                "company_role_fit": 8,
            },
            "only_industry_label": False,
            "relevant_process_or_business_confirmed": True,
            "official_core_evidence": True,
            "sourcing_or_channel_signal_confirmed": False,
            "confidence": "高",
            "entry_barrier": "高",
            "rationale": "EAF process and catalog product fit are confirmed.",
        },
        "confirmed_processes": ["EAF"],
        "confirmed_lining_systems": [],
        "procurement_directions": [
            {
                "product": "Graphite Electrode",
                "priority": "高",
                "application": "EAF steelmaking",
                "evidence_status": "推测",
                "basis": "The official process page confirms EAF; current specification is unknown.",
                "evidence_ids": ["S1"],
                "next_question": "Confirm grade, diameter, nipple system, and trial requirements.",
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


def zero_assessment() -> dict:
    data = assessment()
    data["match"]["components"] = {
        "production_process_need": 0,
        "catalog_fit": 0,
        "consumption_intensity": 0,
        "demand_recurrence": 0,
        "company_role_fit": 0,
    }
    data["match"]["relevant_process_or_business_confirmed"] = False
    data["match"]["rationale"] = "No credible product, process, or channel mapping was confirmed."
    data["confirmed_processes"] = []
    data["procurement_directions"] = []
    return data


def record() -> dict:
    return {
        "id": "company-1",
        "name": "Example Steel",
        "website": "https://example.test",
        "linkedin_url": "https://www.linkedin.com/company/example",
        "industry": "GANG_TIE_YE_JIN",
        "background": "Short CRM background.",
        "updated_at": "2026-08-19T00:00:00Z",
        "contact_count": 2,
        "weakness_reasons": ["背景较短"],
    }


EVIDENCE = """# AnySearch extracted trusted sources

## S1
URL: https://example.test/process
Title: Official process page

The company operates an electric arc furnace and produces steel products. The page describes the production process and plant operations in detail.
"""


class ValidatorTests(unittest.TestCase):
    def test_self_test_covers_project_and_installed_copy(self) -> None:
        for path in (VALIDATOR, Path.home() / ".hermes/skills/aceler-company-research/scripts/validate_assessment.py"):
            result = subprocess.run(["python3", str(path), "--self-test"], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {"valid": True, "tests": 5, "failed": []})

    def test_product_first_schema_accepts_and_scores_down_to_five(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(assessment(), ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])
        self.assertEqual(result["raw_total"], 88)
        self.assertEqual(result["score"], 85)
        self.assertEqual(result["level"], "高")

    def test_missing_boolean_and_out_of_range_components_fail(self) -> None:
        for mutate, message in (
            (lambda data: data["match"]["components"].pop("catalog_fit"), "missing"),
            (lambda data: data["match"].__setitem__("only_industry_label", 1), "boolean"),
            (lambda data: data["match"]["components"].__setitem__("company_role_fit", 11), "range"),
        ):
            data = assessment()
            mutate(data)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "assessment.json"
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                result = validate_assessment(path)
            self.assertFalse(result["valid"], message)

    def test_business_semantics_do_not_hard_fail_the_structure_validator(self) -> None:
        data = assessment()
        data["confirmed_processes"] = []
        data["procurement_directions"] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(validate_assessment(path)["valid"])

        data = assessment()
        data["confirmed_processes"] = ["EAF steelmaking"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])

        data["confirmed_processes"] = ["induction furnace"]
        data["procurement_directions"][0]["product"] = "Graphite Electrode"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])

        data["procurement_directions"][0]["product"] = "Dead Burned Magnesite"
        data["procurement_directions"][0]["evidence_status"] = "已确认"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])

    def test_confidence_evidence_conflict_is_a_warning_not_a_gate(self) -> None:
        data = assessment()
        data["identity_status"] = "ambiguous"
        data["match"]["official_core_evidence"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])
        self.assertTrue(any("review high confidence" in warning for warning in result["warnings"]))


class SeamTests(unittest.TestCase):
    def test_translation_is_a_display_only_fail_open_node(self) -> None:
        canonical = assessment()
        translated = {
            "company_positioning": "官网确认其为 EAF 钢铁生产商。",
            "role_reason": "官方工艺页面确认 EAF 生产。",
            "match_rationale": "EAF 工艺与目录产品适配已经确认。",
            "confirmed_processes": ["EAF"],
            "confirmed_lining_systems": [],
            "procurement_directions": [
                {
                    "application": "EAF 炼钢",
                    "basis": "官方工艺页面确认 EAF；当前规格未知。",
                    "next_question": "确认牌号、直径、接头系统和试用要求。",
                }
            ],
        }
        invocation = {
            "assessment": translated,
            "errors": [],
            "usage": {"total_tokens": 10},
            "seconds": 0.1,
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", return_value=invocation
        ):
            record_dir = Path(directory) / "records" / "001-example"
            record_dir.mkdir(parents=True)
            item = {
                "index": 1,
                "record": record(),
                "status": "valid",
                "assessment": canonical,
                "validation": {"valid": True, "score": 85, "level": "高"},
                "errors": [],
                "record_dir": str(record_dir),
            }
            localize_item(item, Path("/bin/true"), 30, "medium")
            self.assertEqual(item["status"], "valid")
            self.assertEqual(item["assessment"]["company_positioning"]["text"], "Official EAF steel producer.")
            self.assertEqual(item["display_assessment"]["company_positioning"]["text"], "官网确认其为 EAF 钢铁生产商。")
            self.assertEqual(item["display_assessment"]["procurement_directions"][0]["product"], "Graphite Electrode")
            self.assertEqual(item["translation"]["status"], "applied")
            self.assertTrue((record_dir / "localized-assessment.json").is_file())

            broken = copy.deepcopy(item)
            broken.pop("display_assessment")
            broken_translation = copy.deepcopy(translated)
            broken_translation["confirmed_processes"] = ["电弧炉"]
            with patch(
                "company_research_trial.company_research_trial._invoke_hermes",
                return_value={**invocation, "assessment": broken_translation},
            ):
                localize_item(broken, Path("/bin/true"), 30, "medium")
            self.assertEqual(broken["status"], "valid")
            self.assertNotIn("display_assessment", broken)
            self.assertEqual(broken["translation"]["status"], "failed")

            already_chinese = copy.deepcopy(item)
            already_chinese["assessment"] = copy.deepcopy(item["display_assessment"])
            already_chinese.pop("display_assessment")
            with patch("company_research_trial.company_research_trial._invoke_hermes") as mocked:
                localize_item(already_chinese, Path("/bin/true"), 30, "medium")
            mocked.assert_not_called()
            self.assertEqual(already_chinese["translation"]["status"], "not_needed")

    def test_default_hermes_uses_builtin_memory_profile_without_memory_toolset(self) -> None:
        self.assertEqual(DEFAULT_HERMES, Path.home() / ".local" / "bin" / "aceler-memory")
        self.assertEqual(DEFAULT_TOOLSETS, "context_engine")
        self.assertNotIn("memory", DEFAULT_TOOLSETS.split(","))

    def test_prompt_is_short_and_uses_only_current_score_fields(self) -> None:
        prompt = research_prompt(record(), EVIDENCE)
        self.assertIn("$aceler-company-research", prompt)
        for field in ("production_process_need", "catalog_fit", "consumption_intensity", "demand_recurrence", "company_role_fit"):
            self.assertIn(field, prompt)
        self.assertNotIn("purchase_" + "or_channel_likelihood", prompt)
        self.assertNotIn("commercial_" + "access", prompt)
        self.assertIn("FINAL_OUTPUT_LANGUAGE", prompt)
        self.assertTrue(prompt.endswith("只返回 JSON。"))
        self.assertLess(len(prompt), 40000)
        self.assertEqual(prompt.count('"company":'), 2)

    def test_prompt_embeds_the_exact_runtime_contracts(self) -> None:
        prompt = research_prompt(record(), EVIDENCE)
        runtime_report_contract = REPORT_CONTRACT.read_text(encoding="utf-8").split(
            "\nRun `python3 scripts/validate_assessment.py", 1
        )[0].strip()
        self.assertIn(runtime_report_contract, prompt)
        self.assertNotIn("## Final report template", prompt)
        self.assertIn(PRODUCT_CONTRACT.read_text(encoding="utf-8").strip(), prompt)
        self.assertIn("成品内部组分", prompt)
        self.assertIn("运营角色写“终端用户”", prompt)
        self.assertIn("first use evidence to identify the company's main revenue activity", prompt)
        self.assertIn("Judge the commercial relationship to Aceler independently", prompt)

    def test_child_environment_drops_crm_and_mail_credentials(self) -> None:
        with patch.dict("os.environ", {"TWENTY_DB_PASSWORD": "secret", "OUTBOX_TOKEN": "secret", "EMAIL_SECRET": "secret", "GMAIL_TOKEN": "secret", "ANYSEARCH_API_KEY": "ok"}, clear=False):
            environment = child_environment()
        self.assertNotIn("TWENTY_DB_PASSWORD", environment)
        self.assertNotIn("OUTBOX_TOKEN", environment)
        self.assertNotIn("EMAIL_SECRET", environment)
        self.assertNotIn("GMAIL_TOKEN", environment)
        self.assertEqual(environment.get("ANYSEARCH_API_KEY"), "ok")

    def test_identity_seed_name_is_single_bounded_line(self) -> None:
        value = _identity_seed_name('Acme "quoted"\nsite:other.test ' + "x" * 200)
        self.assertNotIn('"', value)
        self.assertNotIn("\n", value)
        self.assertNotIn("site:", value.lower())
        self.assertLessEqual(len(value), 120)

    def test_anysearch_pack_is_identity_seeded_trusted_and_limited_to_two_pages(self) -> None:
        calls: list[list[str]] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            calls.append(args)
            if args[0] == "batch_search":
                return "https://example.test/process\nhttps://example.test/products\nhttps://other.test/nope"
            return "# Official page\n" + "The official company page describes steelmaking process and plant operations. " * 4

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = anysearch_pack(record(), max_sources=2)
        self.assertEqual(meta["search_calls"], 1)
        self.assertEqual(meta["extract_calls"], 2)
        self.assertEqual(len(meta["extracted_urls"]), 2)
        self.assertNotIn("other.test", pack)
        self.assertEqual(pack.count("URL:"), 2)
        self.assertEqual(calls[0][0], "batch_search")
        queries = [calls[0][index + 1] for index, value in enumerate(calls[0]) if value == "--query"]
        self.assertEqual(len(queries), 2)
        self.assertTrue(all("Example Steel" in query for query in queries))
        self.assertTrue(any("official website products company" in query for query in queries))
        self.assertTrue(any("manufacturing plant process furnace kiln" in query for query in queries))

    def test_anysearch_pack_supplements_missing_official_page(self) -> None:
        batch_calls = 0

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            nonlocal batch_calls
            if args[0] == "batch_search":
                batch_calls += 1
                return "" if batch_calls == 1 else "https://www.example.test\nhttps://example.test/operations/smelter"
            if args[1] == "https://example.test":
                return "Error: extract failed"
            return "# Smelter\n" + "The company operates a copper smelter and industrial furnace. " * 4

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            _, meta = anysearch_pack(record(), max_sources=2)
        self.assertEqual(meta["search_calls"], 2)
        self.assertTrue(meta["supplemental_search"])
        self.assertEqual(meta["selected_urls"], ["https://www.example.test", "https://example.test/operations/smelter"])

    def test_anysearch_pack_falls_back_to_identity_seeded_external_result(self) -> None:
        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return "https://industry.test/acme-abrasives"
            if "example.test" in args[1]:
                return "Error: extract failed"
            return "# Industry profile\nAcme manufactures bonded abrasives and grinding wheels. " * 4

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = anysearch_pack(record(), max_sources=2)
        self.assertTrue(meta["external_fallback"])
        self.assertIn("industry.test/acme-abrasives", pack)
        self.assertEqual(meta["selected_urls"], ["https://industry.test/acme-abrasives"])

    def test_anysearch_pack_supports_name_only_identity(self) -> None:
        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return "https://industry.test/acme-abrasives"
            return "# Acme Abrasives\nAcme manufactures bonded abrasives and grinding wheels. " * 4

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = anysearch_pack({"name": "Acme Abrasives"})
        self.assertIn("industry.test/acme-abrasives", pack)
        self.assertTrue(meta["external_fallback"])
        self.assertNotIn("None", meta["query"])

    def test_name_only_pack_prefers_company_process_results_over_generic_profiles(self) -> None:
        search = """
## Query 1: \"Kuwait Ferro Alloys\" official website products company
### 1. Directory profile
- **URL**: https://directory.test/kuwait-ferro-alloys
- Kuwait Ferro Alloys company address and registration details.
### 2. Kuwait Ferro Alloys
- **URL**: https://kuwaitfa.test/products
- Kuwait Ferro Alloys manufactures ferro silicon and steel billets.
## Query 2: \"Kuwait Ferro Alloys\" manufacturing plant process furnace kiln
### 0. Kuwait Ferro Alloys
- **URL**: http://kuwaitfa.test/products
- Kuwait Ferro Alloys manufactures ferro silicon and steel billets.
### 1. Generic ferroalloy production
- **URL**: https://generic.test/ferroalloy-process
- General description of ferroalloy furnaces with no company-specific facts.
### 2. Kuwait Ferro Alloys production
- **URL**: https://industry.test/kuwait-ferro-alloys-production
- Kuwait Ferro Alloys production plant manufactures ferro silicon.
"""

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return search
            return "# Company page\n" + "Company-specific manufacturing and production information. " * 4

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = anysearch_pack({"name": "Kuwait Ferro Alloys"}, max_sources=2)
        self.assertEqual(
            meta["selected_urls"],
            ["https://kuwaitfa.test/products", "https://industry.test/kuwait-ferro-alloys-production"],
        )
        self.assertNotIn("directory.test", pack)
        self.assertNotIn("generic.test", pack)

    def test_name_only_input_gets_internal_id_without_adding_website(self) -> None:
        records = [{"name": "Acme Abrasives"}]
        validated = validate_selected_records(records)
        self.assertEqual(validated, [{"name": "Acme Abrasives", "id": "input-001"}])
        prompt = research_prompt(validated[0], EVIDENCE)
        self.assertNotIn("CRM", prompt.upper())
        marker = next(
            (
                candidate
                for candidate in ("INPUT IDENTITY SEED:\n", "INPUT_IDENTITY_SEED:\n", "IDENTITY SEED:\n")
                if candidate in prompt
            ),
            None,
        )
        self.assertIsNotNone(marker, "prompt must expose a source-neutral identity seed")
        identity = prompt.split(marker, 1)[1].split("\n\nREPORT_CONTRACT", 1)[0]
        self.assertEqual(json.loads(identity), {"company": "Acme Abrasives"})

    def test_prompt_and_zero_review_are_source_neutral_and_non_gating(self) -> None:
        prompt = research_prompt({"name": "Acme Abrasives"}, EVIDENCE)
        lowered_prompt = prompt.lower()
        self.assertNotIn("crm", lowered_prompt)

        # Missing source metadata is unknown, not negative evidence or a reason to lower/zero the fit.
        self.assertTrue(any(term in lowered_prompt for term in ("缺失", "缺少", "missing")))
        self.assertTrue(
            any(
                all(term in lowered_prompt for term in terms)
                for terms in (
                    ("输入", "负面证据"),
                    ("输入", "降分"),
                    ("input", "negative evidence"),
                    ("missing", "lower"),
                )
            ),
            "prompt must say that missing input fields are not a negative scoring signal",
        )
        self.assertTrue(
            any(
                all(term in lowered_prompt for term in terms)
                for terms in (
                    ("采购", "不能降低"),
                    ("采购", "负面证据"),
                    ("procurement", "lower"),
                    ("unpublished procurement", "zero"),
                )
            ),
            "prompt must keep unpublished procurement out of the product/process score",
        )

        review = zero_score_review_prompt(prompt, zero_assessment()).lower()

        def assert_domain_policy(domain_terms: tuple[str, ...], policy_terms: tuple[str, ...]) -> None:
            self.assertTrue(any(term.lower() in review for term in domain_terms), domain_terms)
            self.assertTrue(any(term.lower() in review for term in policy_terms), policy_terms)

        # A confirmed refractory manufacturer and foundry/melting process cannot be zeroed merely
        # because its exact lining or purchase record is not public.
        assert_domain_policy(("耐材", "refractory"), ("非零", "不能为 0", "non-zero", "not zero"))
        assert_domain_policy(("铸造", "熔炼", "foundry", "melting"), ("非零", "不能为 0", "non-zero", "not zero"))
        # Engineering/specification and distribution evidence is a channel route even without a PO.
        assert_domain_policy(("工程", "分销", "engineering", "distribution"), ("渠道", "channel", "规格", "specification"))
        # Superabrasive/diamond adjacency alone must not be mapped to SiC/BFA/WFA.
        self.assertTrue(any(term in review for term in ("superabrasive", "super-abrasive", "超硬", "金刚石", "diamond")))
        self.assertTrue(
            any(
                all(term in review for term in terms)
                for terms in (
                    ("金刚石", "不能"),
                    ("diamond", "not establish"),
                    ("superabrasive", "not enough"),
                    ("super-abrasive", "not imply"),
                )
            ),
            "zero-score review must guard against superabrasive adjacency false positives",
        )

    def test_anysearch_pack_uses_bounded_search_snippets_when_extracts_fail(self) -> None:
        search = "\n".join(
            [
                "## Search Results",
                "### 1. Acme abrasives",
                "- **URL**: https://industry.test/acme",
                "- Acme manufactures grinding wheels and bonded abrasives. " * 3,
                "### 2. Acme profile",
                "- **URL**: https://registry.test/acme",
                "- Registered manufacturer of industrial abrasive products. " * 3,
                "### 3. Unused",
                "- **URL**: https://unused.test/acme",
                "- This third result must not enter the two-source pack. " * 3,
            ]
        )

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            return search if args[0] == "batch_search" else "Error: extract failed"

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = anysearch_pack(record(), max_sources=2)
        self.assertTrue(meta["search_snippet_fallback"])
        self.assertEqual(pack.count("## S"), 2)
        self.assertNotIn("unused.test", pack)

    def test_substantive_extract_allows_error_as_normal_page_text(self) -> None:
        text = "Official process page explains error prevention and steelmaking operations. " * 3
        self.assertTrue(_substantive_extract(text))
        self.assertFalse(_substantive_extract("Error: extract failed " * 10))

    def test_search_result_url_preserves_balanced_parentheses(self) -> None:
        output = "- **URL**: https://registry.test/Acme%20GmbH,%20Berlin%20(Germany)"
        self.assertEqual(_search_result_urls(output)[0], "https://registry.test/Acme%20GmbH,%20Berlin%20(Germany)")

    def test_source_provenance_rejects_url_outside_pack(self) -> None:
        data = assessment()
        data["sources"][0]["url"] = "https://other.test/process"
        errors = anysearch_source_errors(data, EVIDENCE)
        self.assertEqual(len(errors), 1)

    def test_source_provenance_accepts_canonical_url_equivalents(self) -> None:
        data = assessment()
        data["sources"][0]["url"] = "http://www.example.test/process/"
        self.assertEqual(anysearch_source_errors(data, EVIDENCE), [])

    def test_source_provenance_ignores_only_known_tracking_parameters(self) -> None:
        evidence = EVIDENCE.replace(
            "https://example.test/process",
            "https://example.test/process?utm_source=search&srsltid=abc&gclid=123&fbclid=456",
        )
        self.assertEqual(anysearch_source_errors(assessment(), evidence), [])

        data = assessment()
        data["sources"][0]["url"] = "https://example.test/process?document=specification"
        self.assertEqual(len(anysearch_source_errors(data, EVIDENCE)), 1)

    def test_source_provenance_rejects_different_path_or_domain(self) -> None:
        for url in ("https://example.test/other", "https://other.test/process"):
            with self.subTest(url=url):
                data = assessment()
                data["sources"][0]["url"] = url
                errors = anysearch_source_errors(data, EVIDENCE)
                self.assertEqual(len(errors), 1)

    def test_json_parse_has_no_business_normalization(self) -> None:
        value = {"company": "Example", "match": {"components": {"company_role_fit": 3}}}
        self.assertEqual(extract_json_object("```json\n" + json.dumps(value) + "\n```"), value)
        noisy = "```bash\nvalidate input.json\n```\n```json\n" + json.dumps(value) + "\n```\n```bash\ndone\n```"
        self.assertEqual(extract_json_object(noisy), value)
        for raw in (json.dumps(value) + json.dumps(value), "wrapper " + json.dumps(value)):
            with self.assertRaises(ValueError):
                extract_json_object(raw)

    def test_mock_valid_company_calls_hermes_once_and_publishes_valid(self) -> None:
        invocation = {"assessment": assessment(), "errors": [], "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", return_value=invocation) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(item["status"], "valid")
            self.assertEqual(item["validation"]["score"], 85)
            self.assertTrue((Path(item["record_dir"]) / "accepted-assessment.json").is_file())
            self.assertFalse((Path(directory) / ("defer" + "red-companies.json")).exists())

    def test_valid_zero_gets_one_review_and_accepts_a_valid_correction(self) -> None:
        invocations = [
            {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": assessment(), "errors": [], "raw": "corrected", "usage": None, "attempt": {"kind": "zero_score_review", "has_json": True}, "seconds": 0.1},
        ]
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 85)
        self.assertEqual(item["research"]["attempt_count"], 2)
        self.assertEqual(item["research"]["zero_score_review"]["initial_score"], 0)
        self.assertTrue(item["research"]["zero_score_review"]["accepted"])
        self.assertTrue(item["research"]["zero_score_review"]["changed_score"])
        self.assertIn("仅针对首次合法结果为 0%", mocked.call_args_list[1].kwargs["prompt"])
        self.assertEqual(mocked.call_args_list[1].kwargs["raw_path"].name, "hermes-raw-zero-review.txt")

    def test_valid_zero_review_can_keep_zero_without_repeating(self) -> None:
        invocation = {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=[invocation, invocation]) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 0)
        self.assertTrue(item["research"]["zero_score_review"]["accepted"])
        self.assertFalse(item["research"]["zero_score_review"]["changed_score"])

    def test_invalid_zero_review_keeps_the_first_valid_zero(self) -> None:
        invocations = [
            {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": None, "errors": ["Hermes output contains no JSON object"], "raw": "bad", "usage": None, "attempt": {"kind": "zero_score_review", "has_json": False}, "seconds": 0.1},
        ]
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations):
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 0)
        self.assertFalse(item["research"]["zero_score_review"]["accepted"])
        self.assertIn("no JSON", " ".join(item["research"]["zero_score_review"]["errors"]))

    def test_zero_review_can_be_disabled_for_immediate_rollback(self) -> None:
        invocation = {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", return_value=invocation) as mocked:
            item = research_one(
                record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE, review_zero_score=False
            )
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(item["validation"]["score"], 0)
        self.assertFalse(item["research"]["zero_score_review"]["enabled"])
        self.assertFalse(item["research"]["zero_score_review"]["triggered"])

    def test_hermes_command_isolates_ambient_rules(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(assessment()), stderr="")
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run", return_value=completed) as mocked:
            from company_research_trial.company_research_trial import _invoke_hermes

            _invoke_hermes(
                record_dir=Path(directory),
                hermes=Path("/usr/local/bin/hermes"),
                timeout=30,
                reasoning="medium",
                prompt="research",
            )
        command = mocked.call_args.args[0]
        self.assertIn("--ignore-rules", command)
        self.assertNotIn("--skills", command)  # Hermes v0.20.0 oneshot drops it; the contract is embedded in the prompt.

    def test_mock_invalid_company_exhausts_three_attempts(self) -> None:
        invocation = {"assessment": None, "errors": ["Hermes output contains no JSON object"], "raw": "not json", "usage": None, "attempt": {"kind": "research", "has_json": False}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", return_value=invocation) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
            self.assertEqual(mocked.call_count, 3)
            self.assertEqual(item["status"], "failed")
            self.assertEqual(item["research"]["attempt_count"], 3)
            self.assertTrue((Path(item["record_dir"]) / "result.json").is_file())

    def test_mock_invalid_assessment_retries_with_errors_then_stops_on_success(self) -> None:
        invalid = assessment()
        invalid["role_judgment"]["operational_role"] = "invalid-role"
        invocations = [
            {"assessment": invalid, "errors": [], "raw": "invalid", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": assessment(), "errors": [], "raw": "valid", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
        ]
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["research"]["attempt_count"], 2)
        self.assertIn("上次输出未通过校验", mocked.call_args_list[1].kwargs["prompt"])
        self.assertEqual(mocked.call_args_list[0].kwargs["raw_path"].name, "hermes-raw-attempt-1.txt")
        self.assertEqual(mocked.call_args_list[1].kwargs["raw_path"].name, "hermes-raw-attempt-2.txt")

    def test_anysearch_failure_fails_before_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial.anysearch_pack", side_effect=RuntimeError("no trusted page")), patch("company_research_trial.company_research_trial._invoke_hermes") as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"))
        mocked.assert_not_called()
        self.assertEqual(item["status"], "failed")
        self.assertIn("Hermes was not called", " ".join(item["errors"]))

    def test_read_candidates_starts_a_read_only_transaction(self) -> None:
        cursor = Mock()
        cursor.description = [SimpleNamespace(name=name) for name in ("id", "name", "website", "linkedin_url", "industry", "background", "updated_at", "contact_count")]
        cursor.fetchall.return_value = [("1", "Example", "https://example.test", None, "GANG_TIE_YE_JIN", "", None, 0)]
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
        connection.cursor.return_value.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {"TWENTY_WORKSPACE_SCHEMA": "workspace_example"}), patch(
            "company_research_trial.company_research_trial.crm_connection", return_value=connection
        ):
            rows = read_candidates(1)
        self.assertEqual(rows[0]["name"], "Example")
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "BEGIN READ ONLY")
        self.assertIn("%s", cursor.execute.call_args_list[2].args[0])

    def test_reports_have_four_modules_and_only_two_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            run_dir.mkdir(exist_ok=True)
            items = [
                {"index": 1, "record": record(), "status": "valid", "assessment": assessment(), "validation": {"valid": True, "score": 85, "level": "高"}, "errors": []},
                {"index": 2, "record": {**record(), "id": "company-2", "name": "Broken"}, "status": "failed", "assessment": None, "validation": {"valid": False, "errors": ["bad json"]}, "errors": ["bad json"]},
            ]
            markdown, html_path = write_reports(run_dir, items)
            text = markdown.read_text(encoding="utf-8")
            self.assertIn("公司实质定位", text)
            self.assertIn("角色判断", text)
            self.assertIn("匹配度", text)
            self.assertIn("主要采购方向", text)
            self.assertIn("valid", text)
            self.assertIn("failed", text)
            self.assertNotIn("defer" + "red", text)
            self.assertTrue(html_path.is_file())
            self.assertIn('href="https://example.test/process"', html_path.read_text(encoding="utf-8"))


class CliTests(unittest.TestCase):
    def test_run_id_includes_source_and_company_count(self) -> None:
        now = datetime(2026, 8, 27, 7, 15, tzinfo=timezone.utc)
        self.assertEqual(_run_id("file", 5, now), "20260827T071500Z-file-n005")

    def test_anysearch_cli_rejects_missing_binary_without_network(self) -> None:
        with patch("company_research_trial.company_research_trial.ANYSEARCH_CLI", Path("/tmp/no-such-anysearch-cli")):
            with self.assertRaises(RuntimeError):
                run_anysearch_cli(["search", "example"])

    def test_no_zero_review_cli_switch_reaches_each_job(self) -> None:
        item = {
            "index": 1,
            "record": {"name": "RAGS"},
            "status": "valid",
            "assessment": zero_assessment(),
            "validation": {"valid": True, "score": 0, "level": "低"},
            "duration_seconds": 0.1,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected.json"
            selected.write_text('[{"name":"RAGS"}]', encoding="utf-8")
            with patch("company_research_trial.company_research_trial.research_one", return_value=item) as mocked, patch(
                "company_research_trial.company_research_trial.write_reports"
            ):
                exit_code = main(
                    [
                        "--selected-file",
                        str(selected),
                        "--output-root",
                        str(root / "runs"),
                        "--hermes",
                        "/usr/bin/true",
                        "--no-zero-review",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertFalse(mocked.call_args.kwargs["review_zero_score"])




if __name__ == "__main__":
    unittest.main()
