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
    ANYSEARCH_CLI,
    DEFAULT_HERMES,
    DEFAULT_TOOLSETS,
    PROJECT_DIR,
    agentic_anysearch_pack,
    anysearch_pack,
    recall_first_anysearch_pack,
    anysearch_source_errors,
    arbitration_prompt,
    child_environment,
    extract_json_object,
    localize_item,
    main,
    read_candidates,
    research_one,
    research_prompt,
    recall_candidate_prompt,
    low_score_review_prompt,
    zero_score_review_prompt,
    run_anysearch_cli,
    _identity_seed_name,
    _identity_aliases,
    _business_search_name,
    _needs_low_score_review,
    _retrieval_gap_reasons,
    _provenance_url_key,
    _discover_company_domain,
    _direct_material_result_urls,
    _discover_dom_candidates,
    _extract_page_candidates,
    _fallback_extract_output,
    _public_dom_url,
    _run_id,
    _select_relevant_pages,
    _so_results,
    _search_result_urls,
    _wikidata_company_results,
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
            "product_match": 9,
            "commercial_match": 8,
            "follow_up": "跟进",
            "decision_rationale": "Confirmed recurring EAF demand supports follow-up.",
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
    data["match"]["product_match"] = 0
    data["match"]["commercial_match"] = 0
    data["match"]["follow_up"] = "淘汰"
    data["match"]["decision_rationale"] = "No supported product or commercial route."
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
    def test_project_validator_self_test(self) -> None:
        result = subprocess.run(["python3", str(VALIDATOR), "--self-test"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"valid": True, "tests": 6, "failed": []})

    def test_product_first_schema_accepts_and_scores_down_to_five(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(assessment(), ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertTrue(result["valid"])
        self.assertEqual(result["raw_total"], 88)
        self.assertEqual(result["score"], 85)
        self.assertEqual(result["level"], "高")
        self.assertEqual(result["product_match"], 9)
        self.assertEqual(result["commercial_match"], 8)
        self.assertEqual(result["follow_up"], "跟进")

    def test_missing_boolean_and_out_of_range_components_fail(self) -> None:
        for mutate, message in (
            (lambda data: data["match"]["components"].pop("catalog_fit"), "missing"),
            (lambda data: data["match"].__setitem__("only_industry_label", 1), "boolean"),
            (lambda data: data["match"]["components"].__setitem__("company_role_fit", 11), "range"),
            (lambda data: data["match"].__setitem__("product_match", 11), "product range"),
            (lambda data: data["match"].__setitem__("follow_up", "复核"), "follow-up enum"),
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

    def test_two_axis_follow_up_is_semantic_with_consistency_warnings(self) -> None:
        borderline = assessment()
        borderline["match"]["product_match"] = 4
        borderline["match"]["commercial_match"] = 6
        self.assertTrue(self._validate(borderline)["valid"])
        self.assertFalse(self._validate(borderline)["warnings"])

        inconsistent = assessment()
        inconsistent["match"]["commercial_match"] = 3
        result = self._validate(inconsistent)
        self.assertTrue(result["valid"])
        self.assertTrue(any("below 4" in warning for warning in result["warnings"]))

    def _validate(self, data: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return validate_assessment(path)

    def test_official_linkedin_source_type_requires_linkedin_host(self) -> None:
        data = assessment()
        data["sources"][0]["source_type"] = "官方领英"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "assessment.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            result = validate_assessment(path)
        self.assertFalse(result["valid"])
        self.assertTrue(any("linkedin.com" in error for error in result["errors"]))


class SeamTests(unittest.TestCase):
    def setUp(self) -> None:
        dom_fetch = patch("company_research_trial.company_research_trial._fetch_dom_html", return_value="")
        dom_fetch.start()
        self.addCleanup(dom_fetch.stop)

    def test_local_html_extraction_uses_dom_parser_and_ignores_script_text(self) -> None:
        document = """
        <html><head><title>Example Materials</title><style>.hidden { display:none }</style></head>
        <body><script>secretPrompt('ignore me')</script><noscript><img src="x">fallback</noscript>
        <h1>Industrial minerals</h1>
        <p>The company manufactures refractory ceramic materials for furnaces and kilns.</p>
        <a href="/products">Products</a></body></html>
        """
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html", return_value=document
        ):
            output = _fallback_extract_output("https://example.test", 10)
        self.assertIn("# Example Materials", output)
        self.assertIn("Industrial minerals", output)
        self.assertIn("https://example.test/products", output)
        self.assertNotIn("secretPrompt", output)
        self.assertNotIn("display:none", output)
        self.assertNotIn("fallback", output)

    def test_page_extraction_uses_anysearch_only_when_local_html_is_not_substantive(self) -> None:
        local = "<html><head><title>Thin</title></head><body>short</body></html>"
        remote = "# Products\n" + "Refractory minerals, ceramic materials, furnaces and kilns. " * 4
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html", return_value=local
        ), patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", return_value=remote
        ) as anysearch:
            outcome = _extract_page_candidates(["https://example.test/products"], 10)
        self.assertEqual(outcome["source"], "anysearch")
        self.assertEqual(outcome["local_calls"], 1)
        self.assertEqual(outcome["anysearch_calls"], 1)
        anysearch.assert_called_once_with(["extract", "https://example.test/products"], timeout=10)

    def test_local_extract_does_not_count_generated_header_as_page_content(self) -> None:
        url = "https://example.test/a-very-long-path-that-used-to-cross-the-substantive-length-threshold"
        local = "<html><head><title>Products</title></head><body></body></html>"
        remote = "# Products\n" + "Technical ceramic and refractory products. " * 4
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html", return_value=local
        ), patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", return_value=remote
        ) as anysearch:
            outcome = _extract_page_candidates([url], 10)

        self.assertEqual(outcome["source"], "anysearch")
        self.assertEqual(outcome["anysearch_calls"], 1)
        anysearch.assert_called_once_with(["extract", url], timeout=10)

    def test_page_extraction_skips_anysearch_when_local_html_is_substantive(self) -> None:
        local = (
            "<html><head><title>Products</title></head><body><h1>Refractory products</h1><p>"
            + "The company manufactures refractory minerals and ceramic furnace materials. " * 4
            + "</p></body></html>"
        )
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html", return_value=local
        ), patch("company_research_trial.company_research_trial.run_anysearch_cli") as anysearch:
            outcome = _extract_page_candidates(["https://example.test/products"], 10)
        self.assertEqual(outcome["source"], "local_http")
        self.assertEqual(outcome["local_calls"], 1)
        self.assertEqual(outcome["anysearch_calls"], 0)
        anysearch.assert_not_called()

    def test_page_extraction_honors_anysearch_fallback_budget(self) -> None:
        urls = [f"https://example.test/page-{index}" for index in range(6)]
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html", return_value=""
        ), patch(
            "company_research_trial.company_research_trial.run_anysearch_cli",
            side_effect=RuntimeError("blocked"),
        ) as anysearch:
            outcome = _extract_page_candidates(urls, 10, max_anysearch_calls=4)
        self.assertEqual(outcome["local_calls"], 6)
        self.assertEqual(outcome["anysearch_calls"], 4)
        self.assertEqual(anysearch.call_count, 4)

    def test_dom_discovery_canonicalizes_www_before_fetching(self) -> None:
        root = "https://perfectconsultant.test"
        services = f"{root}/services/"
        pages = {
            root: f'<a href="{services}">Services</a>',
            services.rstrip("/"): '<a href="/service/chemicals/">Water treatment chemicals</a>',
        }
        with patch(
            "company_research_trial.company_research_trial._fetch_dom_html",
            side_effect=lambda url, timeout=10: pages.get(url, ""),
        ):
            candidates, fetched = _discover_dom_candidates(
                ["https://www.perfectconsultant.test/en"], "perfectconsultant.test"
            )

        self.assertEqual(fetched, [root, services.rstrip("/")])
        self.assertIn(f"{root}/service/chemicals", [item["url"] for item in candidates])

    def test_dom_fetch_rejects_local_and_cross_domain_redirect_targets(self) -> None:
        self.assertFalse(_public_dom_url("http://127.0.0.1/admin", "example.test"))
        self.assertFalse(_public_dom_url("https://outside.test/page", "example.test"))
        with patch(
            "company_research_trial.company_research_trial.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("8.8.8.8", 443))],
        ):
            self.assertTrue(_public_dom_url("https://docs.example.test/products", "example.test"))

    def test_translation_is_a_display_only_fail_open_node(self) -> None:
        canonical = assessment()
        translated = {
            "company_positioning": "官网确认其为 EAF 钢铁生产商。",
            "role_reason": "官方工艺页面确认 EAF 生产。",
            "match_rationale": "EAF 工艺与目录产品适配已经确认。",
            "decision_rationale": "已确认的持续 EAF 需求支持跟进。",
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
        for field in ("product_match", "commercial_match", "follow_up", "decision_rationale"):
            self.assertIn(field, prompt)
        self.assertIn("本次 JSON 一次返回，不得另开调用", prompt)
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
        self.assertIn("Resolve entity scope semantically", prompt)
        self.assertIn("parent, group, brand, affiliate, division, or site", prompt)
        self.assertIn("polycrystalline", prompt.lower())
        self.assertIn("Calcined Alpha Alumina", prompt)
        self.assertIn("主体归属独立判断", prompt)
        self.assertLess(prompt.index("主体归属独立判断"), prompt.index("source_type"))

    def test_child_environment_drops_crm_and_mail_credentials(self) -> None:
        with patch.dict("os.environ", {"TWENTY_DB_PASSWORD": "secret", "OUTBOX_TOKEN": "secret", "EMAIL_SECRET": "secret", "GMAIL_TOKEN": "secret", "ANYSEARCH_API_KEY": "ok"}, clear=False):
            environment = child_environment()
        self.assertNotIn("TWENTY_DB_PASSWORD", environment)
        self.assertNotIn("OUTBOX_TOKEN", environment)
        self.assertNotIn("EMAIL_SECRET", environment)
        self.assertNotIn("GMAIL_TOKEN", environment)
        self.assertEqual(environment.get("ANYSEARCH_API_KEY"), "ok")

    def test_anysearch_uses_service_key_without_exposing_it_in_process_args(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="results", stderr="")
        with patch.dict("os.environ", {"ANYSEARCH_API_KEY": "new-service-key"}, clear=False), patch(
            "subprocess.run", return_value=completed
        ) as run:
            output = run_anysearch_cli(["search", "Example", "--max_results", "5"])
        self.assertEqual(output, "results")
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("new-service-key", command)
        self.assertEqual(environment["ANYSEARCH_API_KEY"], "new-service-key")
        self.assertEqual(environment["ANYSEARCH_CLI_PATH"], str(ANYSEARCH_CLI))
        self.assertEqual(Path(command[1]).name, "anysearch_bridge.js")

    def test_anysearch_daily_quota_uses_public_web_fallback(self) -> None:
        completed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="API Error: You've reached your API key's total free quota for today.",
        )
        with patch("subprocess.run", return_value=completed), patch(
            "company_research_trial.company_research_trial._public_web_fallback",
            return_value="fallback results",
        ) as fallback:
            output = run_anysearch_cli(["batch_search", "--query", "Example", "--max_results", "5"])
        self.assertEqual(output, "fallback results")
        fallback.assert_called_once()

    def test_anysearch_zero_exit_quota_message_uses_public_web_fallback(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout="Search failed: You've reached your API key's total free quota for today.",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed), patch(
            "company_research_trial.company_research_trial._public_web_fallback",
            return_value="fallback results",
        ) as fallback:
            output = run_anysearch_cli(["search", "Example", "--max_results", "5"])
        self.assertEqual(output, "fallback results")
        fallback.assert_called_once()

    def test_anysearch_extract_failure_uses_public_html_fallback(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="API Error: unable to extract")
        with patch("subprocess.run", return_value=completed), patch(
            "company_research_trial.company_research_trial._public_web_fallback",
            return_value="# Direct page\nReadable company content",
        ) as fallback:
            output = run_anysearch_cli(["extract", "https://example.test/products"])
        self.assertIn("Readable company content", output)
        fallback.assert_called_once_with(["extract", "https://example.test/products"], 90)

    def test_anysearch_explicit_zero_results_uses_public_search_fallback(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="No relevant results found.", stderr="")
        args = ["search", "Example products", "--max_results", "5"]
        with patch("subprocess.run", return_value=completed), patch(
            "company_research_trial.company_research_trial._public_web_fallback",
            return_value="# Public results",
        ) as fallback:
            output = run_anysearch_cli(args)
        self.assertEqual(output, "# Public results")
        fallback.assert_called_once_with(args, 90)

    def test_360_fallback_uses_direct_destination_and_snippet(self) -> None:
        document = b'''<ul class="result"><li class="res-list">
          <h3 class="res-title"><a href="https://www.so.com/link?m=opaque"
          data-mdurl="https://www.example.com/products">Official products</a></h3>
          <p class="res-desc">Calcined alumina and refractory products.</p>
        </li></ul>'''
        response = Mock()
        response.read.return_value = document
        response.headers.get_content_charset.return_value = "utf-8"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch("company_research_trial.company_research_trial.build_opener", return_value=opener):
            results = _so_results("Example products", 5, 30)
        self.assertEqual(
            results,
            [("https://www.example.com/products", "Official products", "Calcined alumina and refractory products.")],
        )

    def test_identity_seed_name_is_single_bounded_line(self) -> None:
        value = _identity_seed_name('Acme "quoted"\nsite:other.test ' + "x" * 200)
        self.assertNotIn('"', value)
        self.assertNotIn("\n", value)
        self.assertNotIn("site:", value.lower())
        self.assertLessEqual(len(value), 120)

    def test_identity_aliases_extracts_english_slash_and_parenthetical_names(self) -> None:
        self.assertIn("Muscat Chemical", _identity_aliases("Muscat Chemical Industries LLC / Muscat Chemical"))
        self.assertIn("FineTech Co., Ltd.", _identity_aliases("한국파인테크 / FineTech Co., Ltd."))
        self.assertIn("PSR", _identity_aliases("Parkinson-Spencer Refractories Ltd（PSR）"))

    def test_business_search_name_avoids_generic_group_alias(self) -> None:
        self.assertEqual(
            _business_search_name("Perfect Solution & Consultant Co., Ltd. / Perfect Group"),
            "Perfect Solution & Consultant Co., Ltd.",
        )
        self.assertEqual(_business_search_name("㈱화인테크（FineTech Co., Ltd.）"), "FineTech Co., Ltd.")
        self.assertEqual(
            _business_search_name("Muscat Chemical Industries LLC / Muscat Chemical"),
            "Muscat Chemical",
        )

    def test_anysearch_pack_uses_concise_alias_for_business_queries(self) -> None:
        calls: list[list[str]] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            calls.append(args)
            if args[0] == "batch_search":
                return "https://finetech.test/products"
            return "# FineTech products\n" + "Advanced ceramic and refractory products. " * 5

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            anysearch_pack({"name": "한국파인테크 / FineTech Co., Ltd."})
        queries = [calls[0][index + 1] for index, value in enumerate(calls[0]) if value == "--query"]
        self.assertIn("한국파인테크 / FineTech Co., Ltd.", queries[0])
        self.assertTrue(all("FineTech Co., Ltd." in query for query in queries[1:]))
        self.assertTrue(all("한국파인테크 /" not in query for query in queries[1:]))

    def test_recall_first_retrieval_replaces_weak_external_pack_once(self) -> None:
        weak = ("weak", {"external_fallback": True, "search_calls": 1, "extract_calls": 2})
        recovered = ("recovered", {"mode": "agentic", "search_calls": 2, "extract_calls": 3})
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.anysearch_pack", return_value=weak
        ) as primary, patch(
            "company_research_trial.company_research_trial.agentic_anysearch_pack", return_value=recovered
        ) as agentic:
            pack, meta = recall_first_anysearch_pack(
                record(), Path(directory), hermes=Path("/bin/true"), refresh_cache=True
            )
        self.assertEqual(pack, "recovered")
        self.assertEqual(primary.call_count, 1)
        self.assertEqual(agentic.call_count, 1)
        self.assertEqual(meta["mode"], "recall_recovery")
        self.assertEqual(meta["search_calls"], 3)
        self.assertEqual(meta["extract_calls"], 5)

    def test_recall_first_requires_semantic_identity_check_for_name_only_input(self) -> None:
        recovered = ("Identity-verified evidence", {"mode": "agentic", "search_calls": 1, "extract_calls": 1})
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.anysearch_pack"
        ) as primary, patch(
            "company_research_trial.company_research_trial.agentic_anysearch_pack", return_value=recovered
        ) as agentic:
            pack, meta = recall_first_anysearch_pack(
                {"name": "Name Only Company"}, Path(directory), hermes=Path("/bin/true")
            )
        self.assertEqual(pack, "Identity-verified evidence")
        self.assertEqual(primary.call_count, 0)
        self.assertEqual(agentic.call_count, 1)
        self.assertEqual(meta["retrieval_route"], "semantic_name_only")
        self.assertEqual(meta["search_calls"], 1)

    def test_recall_first_retrieval_checks_pac_when_water_treatment_is_found(self) -> None:
        weak = (
            "The company manufactures and distributes water treatment chemicals and boiler treatment products.",
            {
                "external_fallback": False,
                "selected_page_scores": [{"categories": ["product", "process"]}],
                "search_calls": 1,
                "extract_calls": 1,
            },
        )
        recovered = ("PAC evidence", {"mode": "agentic", "search_calls": 1, "extract_calls": 1})
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.anysearch_pack", return_value=weak
        ), patch(
            "company_research_trial.company_research_trial.agentic_anysearch_pack", return_value=recovered
        ) as agentic:
            pack, _ = recall_first_anysearch_pack(record(), Path(directory), hermes=Path("/bin/true"))
        self.assertEqual(pack, "PAC evidence")
        self.assertEqual(agentic.call_count, 1)

    def test_recall_first_retrieval_keeps_primary_when_recovery_closes_no_gap(self) -> None:
        primary_pack = "The company manufactures mineral hardeners for industrial floors."
        meta = {"selected_page_scores": [{"categories": ["product"]}], "selected_urls": ["https://a.test"]}
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.anysearch_pack", return_value=(primary_pack, meta)
        ), patch(
            "company_research_trial.company_research_trial.agentic_anysearch_pack",
            return_value=("Industrial floor hardener company", {"mode": "agentic"}),
        ):
            pack, result_meta = recall_first_anysearch_pack(record(), Path(directory), hermes=Path("/bin/true"))
        self.assertEqual(pack, primary_pack)
        self.assertFalse(result_meta["recall_recovery"]["accepted"])

    def test_recall_first_does_not_restore_primary_after_semantic_identity_rejection(self) -> None:
        weak = ("Wrong namesake", {"external_fallback": True})
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.anysearch_pack", return_value=weak
        ), patch(
            "company_research_trial.company_research_trial.agentic_anysearch_pack",
            side_effect=RuntimeError("Hermes selected no URL from the AnySearch results"),
        ):
            with self.assertRaisesRegex(RuntimeError, "selected no URL"):
                recall_first_anysearch_pack(record(), Path(directory), hermes=Path("/bin/true"))

    def test_wikidata_company_results_exposes_only_claimed_official_urls(self) -> None:
        search_response = Mock()
        search_response.read.return_value = json.dumps({"search": [{"id": "Q7194993"}]}).encode()
        search_response.__enter__ = Mock(return_value=search_response)
        search_response.__exit__ = Mock(return_value=False)
        entity_response = Mock()
        entity_response.read.return_value = json.dumps(
            {
                "entities": {
                    "Q7194993": {
                        "labels": {"en": {"value": "Pindad"}},
                        "descriptions": {"en": {"value": "Indonesian industrial company"}},
                        "claims": {"P856": [{"mainsnak": {"datavalue": {"value": "https://pindad.com"}}}]},
                    }
                }
            }
        ).encode()
        entity_response.__enter__ = Mock(return_value=entity_response)
        entity_response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.side_effect = [search_response, entity_response]
        with patch("company_research_trial.company_research_trial.build_opener", return_value=opener):
            output = _wikidata_company_results(["Pindad"])
        self.assertIn("https://pindad.com", output)
        self.assertIn("Q7194993", output)

    def test_direct_material_supplement_reserves_official_catalog_result(self) -> None:
        search = """
### 1. Generic products
- **URL**: https://korodur.test/products
- Industrial floor systems.
### 2. KORODUR Diamond Concrete
- **URL**: https://korodur.test/product/diamond-concrete
- Hard aggregate produced from electrocorundum and silicon carbide.
### 3. Unrelated silicon carbide
- **URL**: https://other.test/sic
- Silicon carbide powder.
"""
        self.assertEqual(
            _direct_material_result_urls(search, "korodur.test"),
            ["https://korodur.test/product/diamond-concrete"],
        )

    def test_retrieval_gaps_include_unresolved_alumina_grade_and_supplier_portfolio(self) -> None:
        meta = {"selected_page_scores": [{"categories": ["product", "process"]}]}
        alumina = "The company supplies aluminum oxide ceramic raw materials to refractory and abrasive industries."
        supplier = "A specialty raw materials distributor serving refractory, ceramic and steel industries."
        self.assertIn("alumina_producer_without_grade", _retrieval_gap_reasons(meta, alumina))
        self.assertIn("target_industry_supplier_without_portfolio", _retrieval_gap_reasons(meta, supplier))

    def test_provenance_url_key_treats_percent_escape_hex_case_as_the_same_url(self) -> None:
        lower = "https://example.test/service/%e0%b9%80%e0%b8%84%e0%b8%a1%e0%b8%b5"
        mixed = "https://www.example.test/service/%E0%b9%80%E0%b8%84%E0%B8%A1%E0%B8%B5/"
        self.assertEqual(_provenance_url_key(lower), _provenance_url_key(mixed))

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
        self.assertEqual(meta["extract_calls"], 3)
        self.assertEqual(len(meta["extracted_urls"]), 3)
        self.assertNotIn("other.test", pack)
        self.assertEqual(pack.count("URL:"), 2)
        self.assertEqual(calls[0][0], "batch_search")
        queries = [calls[0][index + 1] for index, value in enumerate(calls[0]) if value == "--query"]
        self.assertEqual(len(queries), 4)
        self.assertTrue(all("Example Steel" in query for query in queries))
        self.assertTrue(any("official website company" in query for query in queries))
        self.assertTrue(any("products materials minerals" in query for query in queries))
        self.assertTrue(any("manufacturing plant process applications" in query for query in queries))
        self.assertTrue(any("distributor supplier engineering" in query for query in queries))

    def test_anysearch_pack_preserves_fixed_query_slot_candidates(self) -> None:
        search = """
## Query 1: identity
- **URL**: https://slot.test
- Official company website.
## Query 2: offering
- **URL**: https://slot.test/products
- Refractory mineral products and materials.
## Query 3: process
- **URL**: https://slot.test/applications
- Furnace, kiln and foundry applications.
## Query 4: commercial
- **URL**: https://slot.test/distribution
- Distribution and technical service network.
"""

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return search
            return "# Official evidence\n" + "Products, manufacturing, applications and distribution. " * 5

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            _, meta = anysearch_pack({"name": "Slot"}, max_sources=3)
        self.assertEqual(meta["candidate_manifest"]["identity"], ["https://slot.test"])
        self.assertEqual(meta["candidate_manifest"]["offering"], ["https://slot.test/products"])
        self.assertEqual(meta["candidate_manifest"]["process"], ["https://slot.test/applications"])
        self.assertEqual(meta["candidate_manifest"]["commercial"], ["https://slot.test/distribution"])
        self.assertIn("https://slot.test/products", meta["selected_urls"])

    def test_anysearch_pack_cache_freezes_candidates_and_evidence_until_refresh(self) -> None:
        version = 1
        calls: list[list[str]] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            calls.append(args)
            if args[0] == "batch_search":
                return (
                    "## Query 1: identity\n"
                    f"- **URL**: https://cache.test/v{version}\n- Official company website.\n"
                    "## Query 2: offering\n## Query 3: process\n## Query 4: commercial\n"
                )
            return f"# Cached evidence v{version}\n" + f"Industrial materials version {version}. " * 5

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ):
            pack1, meta1 = anysearch_pack({"name": "Cache"}, cache_dir=Path(directory))
            first_call_count = len(calls)
            version = 2
            pack2, meta2 = anysearch_pack({"name": "Cache"}, cache_dir=Path(directory))
            pack3, meta3 = anysearch_pack(
                {"name": "Cache"}, cache_dir=Path(directory), refresh_cache=True
            )
            _, meta4 = anysearch_pack(
                {"name": "Cache", "country": "Germany"}, cache_dir=Path(directory)
            )
        self.assertEqual(pack1, pack2)
        self.assertEqual(first_call_count, meta1["search_calls"] + meta1["extract_calls"])
        self.assertEqual(len(calls), first_call_count * 3)
        self.assertTrue(meta2["cache_hit"])
        self.assertEqual(meta2["search_calls"], 0)
        self.assertEqual(meta2["extract_calls"], 0)
        self.assertNotEqual(pack2, pack3)
        self.assertFalse(meta3["cache_hit"])
        self.assertFalse(meta4["cache_hit"])

    def test_agentic_anysearch_pack_uses_fixed_queries_and_lets_hermes_select(self) -> None:
        invocations = [
            {"assessment": {"queries": ['"RATH Gruppe" refractory official']}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": [
                        "https://www.rath-group.test/en/products",
                    ],
                    "reason": "The refractory manufacturer is the rath-group.test entity.",
                },
                "errors": [],
                "usage": None,
                "attempt": {"kind": "retrieval_select", "has_json": True},
                "seconds": 0.1,
            },
            {
                "assessment": {
                    "missing_evidence": [],
                    "supplemental_queries": [],
                    "reason": "The official product page is sufficient for this bounded evidence pack.",
                },
                "errors": [],
                "usage": None,
                "attempt": {"kind": "retrieval_gap_check", "has_json": True},
                "seconds": 0.1,
            },
        ]
        search_output = """
### 1. RATH refractory products
- **URL**: https://www.rath-group.test/en/products
- RATH manufactures refractory products and insulation systems.
### 2. RATH rail company
- **URL**: https://rail-rath.test/about
- Passenger rail operator.
"""

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return search_output
            self.assertEqual(args, ["extract", "https://www.rath-group.test/en/products"])
            return "# Products\nRATH manufactures refractory products, furnace linings, and insulation systems. " * 4

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as hermes, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ):
            pack, meta = agentic_anysearch_pack(
                {"name": "RATH Gruppe"}, Path(directory), hermes=Path("/bin/true"), max_sources=2
            )

        self.assertEqual(hermes.call_count, 3)
        self.assertEqual(meta["mode"], "agentic")
        self.assertEqual(meta["planner_mode"], "hermes_semantic")
        self.assertIsNone(meta["planner_usage"])
        self.assertEqual(meta["search_calls"], 1)
        self.assertEqual(meta["extract_calls"], 0)
        self.assertGreaterEqual(meta["local_extract_calls"], 1)
        self.assertEqual(meta["identity_status"], "confirmed")
        self.assertEqual(meta["selected_urls"], ["https://www.rath-group.test/en/products"])
        self.assertIn("rath-group.test/en/products", pack)
        self.assertNotIn("rail-rath.test", pack)
        self.assertIn("Calcium Aluminate Cement & PAC", hermes.call_args_list[1].kwargs["prompt"])
        self.assertIn("untrusted", hermes.call_args_list[1].kwargs["prompt"].lower())

    def test_agentic_anysearch_pack_uses_semantic_planner_before_search(self) -> None:
        planner_usage = {"input_tokens": 123}
        invocations = [
            {
                "assessment": {
                    "queries": [
                        '"Acme Refractory Group" official manufacturer',
                        '"Acme Refractory" refractory products plant',
                    ]
                },
                "errors": [],
                "usage": planner_usage,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": ["https://acme-refractory.test/products"],
                    "supplemental_queries": [],
                    "reason": "Official manufacturer product page.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "missing_evidence": [],
                    "supplemental_queries": [],
                    "reason": "The official product page is sufficient.",
                },
                "errors": [],
                "usage": None,
            },
        ]
        batch_calls: list[list[str]] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                batch_calls.append(args)
                return "- **URL**: https://acme-refractory.test/products\n- Official refractory manufacturer."
            return "# Products\nAcme manufactures refractory bricks and furnace linings. " * 5

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as hermes, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ):
            pack, meta = agentic_anysearch_pack(
                {"name": "Acme Refractory"}, Path(directory), hermes=Path("/bin/true"), max_sources=2
            )

        self.assertEqual(hermes.call_count, 3)
        self.assertEqual(len(batch_calls), 1)
        self.assertIn("Semantically plan", hermes.call_args_list[0].kwargs["prompt"])
        self.assertEqual(hermes.call_args_list[0].kwargs["attempt_kind"], "retrieval_plan")
        self.assertIn('"Acme Refractory Group" official manufacturer', batch_calls[0])
        self.assertEqual(meta["planner_mode"], "hermes_semantic")
        self.assertEqual(meta["planner_usage"], planner_usage)
        self.assertEqual(meta["search_calls"], 1)
        self.assertIn("acme-refractory.test/products", pack)

    def test_agentic_anysearch_pack_rejects_a_url_not_returned_by_anysearch(self) -> None:
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": ["https://hallucinated.test/products"],
                    "reason": "unsupported",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ), patch(
            "company_research_trial.company_research_trial.run_anysearch_cli",
            return_value="- **URL**: https://example.test/products",
        ) as anysearch:
            with self.assertRaisesRegex(RuntimeError, "selected no URL"):
                agentic_anysearch_pack({"name": "Example Steel"}, Path(directory), hermes=Path("/bin/true"))
        self.assertEqual(anysearch.call_count, 1)

    def test_agentic_anysearch_pack_can_run_one_bounded_supplemental_search(self) -> None:
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": ["https://perfect.test/about"],
                    "supplemental_queries": ['site:perfect.test "Poly Aluminum Chloride"'],
                    "reason": "The identity is confirmed but the handled chemical portfolio needs verification.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
            {
                "assessment": {
                    "missing_evidence": ["products_or_materials"],
                    "supplemental_queries": ['site:perfect.test "Poly Aluminum Chloride"'],
                    "reason": "The extracted official page confirms water treatment but not PAC.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": ["https://perfect.test/pac", "https://perfect.test/about"],
                    "supplemental_queries": [],
                    "reason": "The official PAC product page establishes direct catalog overlap.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
        ]
        searches = [
            "- **URL**: https://perfect.test/about\n- Environmental engineering and water treatment company.",
            "- **URL**: https://perfect.test/pac\n- Poly Aluminum Chloride product for water treatment.",
        ]

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return searches.pop(0)
            return "# Product\nPoly Aluminum Chloride is supplied for industrial water treatment. " * 4

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as hermes, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ):
            pack, meta = agentic_anysearch_pack(
                {"name": "Perfect Solution & Consultant"},
                Path(directory),
                hermes=Path("/bin/true"),
                max_sources=2,
            )

        self.assertEqual(hermes.call_count, 4)
        first_selection_prompt = hermes.call_args_list[1].kwargs["prompt"]
        self.assertIn("water treatment", first_selection_prompt)
        self.assertIn("Poly Aluminum Chloride", first_selection_prompt)
        self.assertEqual(meta["search_calls"], 2)
        self.assertEqual(
            meta["supplemental_queries"],
            ['site:perfect.test ("Poly Aluminum Chloride" OR "Poly Aluminium Chloride" OR PAC)'],
        )
        self.assertEqual(meta["selected_urls"][0], "https://perfect.test/pac")
        self.assertIn("Poly Aluminum Chloride", pack)

    def test_agentic_anysearch_pack_extracts_plausible_official_site_before_accepting_no_gap(self) -> None:
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": [
                        "https://workventure.test/company/perfect-consultant",
                        "https://enwastexpo.test/exhibitor/perfect-consultant",
                    ],
                    "supplemental_queries": [],
                    "reason": "The exhibitor page appears to identify the target.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
            {
                "assessment": {
                    "missing_evidence": ["products_or_materials", "scale", "transaction_role"],
                    "supplemental_queries": [
                        'Perfect Consultant ("Poly Aluminum Chloride" OR PAC)'
                    ],
                    "reason": "The extracted official site confirms water treatment but not the chemical portfolio.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": [
                        "https://perfectconsultant.test/products/pac",
                        "https://perfectconsultant.test",
                    ],
                    "supplemental_queries": [],
                    "reason": "The official pages confirm the identity and PAC portfolio.",
                },
                "errors": [],
                "usage": None,
                "attempt": {},
                "seconds": 0.1,
            },
        ]
        searches = [
            """
### 1. Perfect Consultant company profile
- **URL**: https://workventure.test/company/perfect-consultant
- Perfect Solution & Consultant company profile and environmental services.
### 2. ENWASTEXPO exhibitor
- **URL**: https://enwastexpo.test/exhibitor/perfect-consultant
- Environmental services exhibitor profile.
""",
            """
### 1. PAC product
- **URL**: https://perfectconsultant.test/products/pac
- Poly Aluminum Chloride for industrial water treatment.
""",
        ]
        extracts = {
            "https://workventure.test/company/perfect-consultant": (
                "# Company profile\nWebsite:www.perfectconsultant.test\n"
                + "Perfect Solution & Consultant provides environmental and water treatment services. " * 4
            ),
            "https://perfectconsultant.test": (
                "# Perfect Solution & Consultant\n"
                + "Official environmental engineering, water treatment, and wastewater project services. " * 4
            ),
            "https://enwastexpo.test/exhibitor/perfect-consultant": (
                "# Exhibitor profile\nPerfect Consultant provides environmental services. " * 4
            ),
            "https://perfectconsultant.test/products/pac": (
                "# Poly Aluminum Chloride\nPAC is supplied for industrial water treatment. " * 4
            ),
        }
        cli_calls: list[list[str]] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            cli_calls.append(args)
            if args[0] == "batch_search":
                return searches.pop(0)
            return extracts[args[1]]

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as hermes, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ):
            pack, meta = agentic_anysearch_pack(
                {"name": "Perfect Solution & Consultant"},
                Path(directory),
                hermes=Path("/bin/true"),
                max_sources=2,
            )

        self.assertEqual(hermes.call_count, 4)
        self.assertIn('"Perfect Solution & Consultant" official website', cli_calls[0])
        gap_prompt = hermes.call_args_list[2].kwargs["prompt"]
        self.assertIn("water treatment", gap_prompt)
        self.assertIn("Poly Aluminum Chloride", gap_prompt)
        self.assertEqual(meta["reserved_official_url"], "https://www.perfectconsultant.test")
        self.assertEqual(
            meta["extract_fallbacks"],
            [{"from": "https://www.perfectconsultant.test", "to": "https://perfectconsultant.test"}],
        )
        self.assertEqual(meta["reserved_supplemental_url"], "https://perfectconsultant.test/products/pac")
        self.assertTrue(meta["official_candidate_extracted"])
        self.assertEqual(meta["search_calls"], 2)
        self.assertTrue(meta["supplemental_queries"][0].startswith("site:perfectconsultant.test "))
        self.assertIn("https://perfectconsultant.test", meta["selected_urls"])
        self.assertIn("https://perfectconsultant.test/products/pac", meta["selected_urls"])
        self.assertIn("Poly Aluminum Chloride", pack)

    def test_agentic_anysearch_pack_retries_product_query_when_supplement_reveals_official_domain(self) -> None:
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "ambiguous",
                    "selected_urls": ["https://directory.test/perfect-consultant"],
                    "supplemental_queries": [],
                    "reason": "Only a water-treatment directory profile is available.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "missing_evidence": ["products_or_materials"],
                    "official_website_query": '"Perfect Consultant" water treatment official website',
                    "supplemental_queries": ['"Perfect Consultant" PAC water treatment'],
                    "reason": "The handled treatment chemical is missing.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": ["https://perfectconsultant.test/pac", "https://perfectconsultant.test"],
                    "supplemental_queries": [],
                    "reason": "Official identity and PAC pages are available.",
                },
                "errors": [],
                "usage": None,
            },
        ]
        searches = [
            "- **URL**: https://directory.test/perfect-consultant\n- Water treatment company profile.",
            "- **URL**: https://perfectconsultant.test\n- Official environmental company site.",
            "- **URL**: https://perfectconsultant.test/pac\n- Official Poly Aluminum Chloride page.",
        ]
        extracts = {
            "https://directory.test/perfect-consultant": "# Profile\nWater and wastewater treatment services. " * 5,
            "https://perfectconsultant.test": "# Official\nEnvironmental and water treatment company. " * 5,
            "https://perfectconsultant.test/pac": "# PAC\nPoly Aluminum Chloride for water treatment. " * 5,
        }

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            return searches.pop(0) if args[0] == "batch_search" else extracts[args[1]]

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ), patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = agentic_anysearch_pack(
                {"name": "Perfect Solution & Consultant"},
                Path(directory),
                hermes=Path("/bin/true"),
                max_sources=2,
            )

        self.assertEqual(meta["search_calls"], 3)
        self.assertTrue(meta["supplemental_retry_query"].startswith("site:perfectconsultant.test "))
        self.assertEqual(meta["reserved_supplemental_url"], "https://perfectconsultant.test/pac")
        self.assertIn("https://perfectconsultant.test", meta["selected_urls"])
        self.assertIn("https://perfectconsultant.test/pac", meta["selected_urls"])
        self.assertIn("Poly Aluminum Chloride", pack)

    def test_agentic_anysearch_pack_keeps_evidence_when_identity_remains_ambiguous(self) -> None:
        root = "https://target.test"
        product = "https://target.test/products"
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "ambiguous",
                    "selected_urls": [root],
                    "supplemental_queries": ['"Target s.r.o." products'],
                    "reason": "The group site is plausible but the legal entity is unresolved.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "ambiguous",
                    "missing_evidence": ["products_or_materials"],
                    "official_website_query": "",
                    "supplemental_queries": ['"Target s.r.o." products'],
                    "reason": "More product evidence is needed.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "ambiguous",
                    "selected_urls": [root, product],
                    "supplemental_queries": [],
                    "reason": "Product evidence exists, but the legal relationship is unresolved.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "ambiguous",
                    "missing_evidence": [],
                    "official_website_query": "",
                    "supplemental_queries": [],
                    "reason": "Keep the identity caveat.",
                },
                "errors": [],
                "usage": None,
            },
        ]
        searches = [
            f"- **URL**: {root}\n- Target group homepage.",
            f"- **URL**: {product}\n- Target high-temperature insulation products.",
        ]
        extracts = {
            root: "# Target group\nHigh-temperature industrial insulation manufacturer. " * 5,
            product: "# Products\nCeramic fibre and refractory insulation products. " * 5,
        }

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            return searches.pop(0) if args[0] == "batch_search" else extracts[args[1]]

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ), patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            pack, meta = agentic_anysearch_pack(
                {"name": "Target s.r.o.", "website": root},
                Path(directory),
                hermes=Path("/bin/true"),
                max_sources=2,
            )

        self.assertTrue(meta["identity_unresolved_after_retry"])
        self.assertEqual(meta["gap_identity_status"], "ambiguous")
        self.assertIn("Ceramic fibre", pack)

    def test_agentic_anysearch_pack_uses_one_dom_selection_instead_of_recursive_gap_checks(self) -> None:
        root = "https://perfectconsultant.test"
        services = "https://perfectconsultant.test/services/"
        chemical = "https://perfectconsultant.test/service/water-treatment-chemicals/"
        invocations = [
            {"assessment": {"queries": []}, "errors": [], "usage": None},
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": [root],
                    "supplemental_queries": [],
                    "reason": "Official identity page.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "selected_ids": ["D2", "D999"],
                    "reason": "The chemical card is the strongest catalog-overlap candidate.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "missing_evidence": [],
                    "supplemental_queries": [],
                    "reason": "The official identity and product page are sufficient.",
                },
                "errors": [],
                "usage": None,
            },
            {
                "assessment": {
                    "identity_status": "confirmed",
                    "selected_urls": [root, chemical.rstrip("/")],
                    "supplemental_queries": [],
                    "reason": "Official identity and PAC product evidence are available.",
                },
                "errors": [],
                "usage": None,
            },
        ]
        extracts = {
            root: "# Official\nWater and wastewater environmental services. " * 5,
            chemical.rstrip("/"): (
                "# Water treatment chemicals\nPoly Aluminum Chloride (PAC) is produced and distributed. " * 5
            ),
        }
        dom_html = {
            root: (
                '<html><body><p>Perfect Solution &amp; Consultant provides environmental '
                'engineering, industrial water treatment, and wastewater project services '
                'for commercial customers.</p>'
                f'<nav><a href="{services}">Services</a></nav></body></html>'
            ),
            services.rstrip("/"): (
                '<html><body><section><h2>Water treatment chemicals</h2>'
                f'<a href="{chemical}">Chemicals for producing tap water and treating wastewater</a>'
                '<a href="https://outside.test/trap">Untrusted external link</a></section></body></html>'
            ),
        }
        searches = [
            f"- **URL**: {root}\n- Official environmental and water-treatment company.",
            f"- **URL**: {chemical.rstrip('/')}\n- Poly Aluminum Chloride for water treatment.",
        ]

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return searches.pop(0)
            return extracts[args[1]]

        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as hermes, patch(
            "company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli
        ), patch(
            "company_research_trial.company_research_trial._fetch_dom_html",
            side_effect=lambda url, timeout=10: dom_html.get(url, ""),
            create=True,
        ):
            pack, meta = agentic_anysearch_pack(
                {"name": "Perfect Solution & Consultant"},
                Path(directory),
                hermes=Path("/bin/true"),
                max_sources=3,
            )

        self.assertEqual(hermes.call_count, 5)
        self.assertIn("DOM LINK CANDIDATES", hermes.call_args_list[2].kwargs["prompt"])
        self.assertIn("Do not decide whether the company is relevant", hermes.call_args_list[2].kwargs["prompt"])
        self.assertEqual(meta["search_calls"], 2)
        self.assertEqual(meta["planner_mode"], "hermes_semantic")
        self.assertIsNone(meta["planner_usage"])
        self.assertEqual(meta["retrieval_strategy"], "dom_inventory")
        self.assertEqual(meta["dom_selected_urls"], [chemical.rstrip("/")])
        self.assertNotIn("https://outside.test/trap", meta["dom_selected_urls"])
        self.assertIn(root, meta["selected_urls"])
        self.assertIn(chemical.rstrip("/"), meta["selected_urls"])
        self.assertIn("Poly Aluminum Chloride", pack)

    def test_page_reranking_drops_career_and_preserves_evidence_diversity(self) -> None:
        pages = [
            ("https://nabaltec.test/en/career/what-we-offer", "# Careers\nEmployee benefits and vacancies. " * 8),
            ("https://nabaltec.test/en/products", "# Products\nAlumina, boehmite and ceramic raw material products. " * 8),
            ("https://nabaltec.test/en/production", "# Production\nManufacturing plant, calcination process and kiln technology. " * 8),
            ("https://nabaltec.test/en/download/tds.pdf", "# Technical data\nProduct grade datasheet and technical properties. " * 8),
        ]
        selected, diagnostics = _select_relevant_pages(pages, "Nabaltec AG", "nabaltec.test", 3)
        urls = [url for url, _ in selected]
        self.assertNotIn("https://nabaltec.test/en/career/what-we-offer", urls)
        self.assertIn("https://nabaltec.test/en/products", urls)
        self.assertIn("https://nabaltec.test/en/production", urls)
        self.assertEqual(len(diagnostics), 3)

    def test_page_reranking_prefers_application_page_over_history_navigation(self) -> None:
        shared_navigation = (
            "# Nabaltec\nProducts applications markets company history manufacturing "
            "plant ceramic mineral technical data. " * 8
        )
        history = "https://nabaltec.test/en/company/history"
        applications = "https://nabaltec.test/en/market-applications"
        selected, _ = _select_relevant_pages(
            [(history, shared_navigation), (applications, shared_navigation)],
            "Nabaltec AG",
            "nabaltec.test",
            1,
        )
        self.assertEqual(selected[0][0], applications)

    def test_name_only_domain_discovery_prefers_company_host_over_directories(self) -> None:
        urls = [
            "https://www.europages.co.uk/REFRASIL-SRO/CZE079978-00101.html",
            "https://www.scribd.com/document/235244255/refractories",
            "https://www.refrasil.cz/english/about-us",
        ]
        self.assertEqual(_discover_company_domain(urls, "REFRASIL, s.r.o."), "refrasil.cz")

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

    def test_anysearch_pack_follows_two_bounded_official_intent_links(self) -> None:
        home = "https://www.nabaltec.test/en"
        development = "https://www.nabaltec.test/en/company/development-application-technology"
        products = "https://www.nabaltec.test/en/products"
        applications = "https://www.nabaltec.test/en/market-applications"
        search = f"- **URL**: {home}\n- Official Nabaltec website."
        extracts = {
            home: (
                "# Home\n"
                f"[Development & Application Technology]({development})\n"
                f"[Products]({products})\n"
                f"[Market & Applications]({applications})\n"
                "Nabaltec manufactures specialty mineral products for industrial markets. " * 4
            ),
            development: "# Development\nResearch and application technology services. " * 5,
            products: "# Products\nAluminum oxide and ceramic bodies for industrial applications. " * 5,
            applications: "# Applications\nCeramics, refractories and polishing applications. " * 5,
        }

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            return search if args[0] == "batch_search" else extracts[args[1]]

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            _, meta = anysearch_pack({"name": "Nabaltec AG"}, max_sources=3)
        self.assertIn(products, meta["selected_urls"])
        self.assertIn(applications, meta["selected_urls"])
        self.assertNotIn(development, meta["selected_urls"])
        self.assertEqual(meta["linked_candidates"][:2], [products, applications])

    def test_anysearch_pack_bounds_failed_link_expansion_attempts(self) -> None:
        home = "https://bounded.test"
        links = [f"https://bounded.test/products/{index}" for index in range(3)]
        search = f"- **URL**: {home}\n- Official bounded company website."
        attempted: list[str] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return search
            attempted.append(args[1])
            if args[1] == home:
                navigation = "\n".join(f"[Product {index}]({url})" for index, url in enumerate(links))
                return f"# Home\n{navigation}\nIndustrial mineral products. " * 4
            return "Error: extract failed " * 10

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            anysearch_pack({"name": "Bounded"}, max_sources=3)
        self.assertEqual(attempted, [home, *links[:2]])

    def test_anysearch_pack_ignores_low_intent_news_and_contact_links(self) -> None:
        home = "https://cofermin.test/en/fireproof"
        news = "https://cofermin.test/en/latest"
        contact = "https://cofermin.test/contact"
        search = f"- **URL**: {home}\n- Official refractory material distributor."
        attempted: list[str] = []

        def fake_cli(args: list[str], timeout: int = 90) -> str:
            if args[0] == "batch_search":
                return search
            attempted.append(args[1])
            return (
                f"# Fireproof\n[Latest]({news}) [Contact]({contact})\n"
                "Distributor of refractory minerals and industrial raw materials. " * 4
            )

        with patch("company_research_trial.company_research_trial.run_anysearch_cli", side_effect=fake_cli):
            _, meta = anysearch_pack({"name": "Cofermin"}, max_sources=3)
        self.assertEqual(attempted, [home])
        self.assertEqual(meta["linked_candidates"], [])

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
        self.assertEqual(meta["selected_urls"], ["https://kuwaitfa.test/products"])
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
        self.assertIn("合理工业推断", prompt)
        self.assertIn("不能只计入上限 10 分的 company_role_fit", prompt)
        self.assertIn("吞吐/采购未公开不得否定该路径", prompt)
        self.assertIn("有证据的 PAC/PACl 制造、销售/分销或持续投加", prompt)
        self.assertIn("其他目录品无关", prompt)
        self.assertIn("competitive status is not a zero-score reason", prompt)
        self.assertIn("材料生产商", prompt)
        self.assertIn("供应合作伙伴", prompt)
        self.assertIn("产品组合合作伙伴", prompt)
        self.assertIn("recurring use", prompt)
        self.assertIn("independent of refractories", prompt)
        self.assertIn("high-purity technical ceramics retain product fit", prompt)
        self.assertIn("合理原料投入路线不因私有规格或供应商未公开而消失", prompt)
        self.assertNotIn("product_match>=5、commercial_match=4时使用4分跟进例外", prompt)
        self.assertIn("product_match>=5、commercial_match=4不是自动跟进规则", prompt)
        self.assertIn("必须引用公司级证据支持的具体商业动作", prompt)
        self.assertIn("设备制造、EPC或客户行业不能代替", prompt)
        self.assertIn("高纯氧化铝陶瓷", prompt)
        self.assertIn("不得以 commercial_match<4 跟进", prompt)
        self.assertIn("结构化主体判断只是提醒", prompt)
        self.assertIn("仍要根据实质定位评分", prompt)
        self.assertIn("已确认的公司级实质经营活动高于宽泛行业标签", prompt)
        self.assertIn("政府/注册来源明确列出具体制造活动", prompt)
        self.assertIn("不得写成已确认当前产线", prompt)
        self.assertIn("不设置固定底分", prompt)
        self.assertIn("公司规模与物料吞吐必须影响 consumption_intensity", prompt)
        self.assertIn("必须影响 company_role_fit 和整体商业优先级", prompt)
        self.assertIn("安装或转售成品不证明采购其上游原料", prompt)
        self.assertIn("历史经营证据不能单独支持当前潜在客户", prompt)
        self.assertNotIn("公司规模、竞争关系和来源数量都不得降低", prompt)
        self.assertNotIn("若证据包将 identity 标为 ambiguous", prompt)
        self.assertNotIn("4+5+2+2+2=15", prompt)

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
        self.assertIn("不得把“未确认具体目录品”等同于“所有分项必须为 0”", review)

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

    def test_arbiter_receives_exact_disputed_product_rules_without_the_full_catalog(self) -> None:
        lead = assessment()
        recall = assessment()
        recall["procurement_directions"] = [
            {**recall["procurement_directions"][0], "product": "Fumed Silica"}
        ]
        prompt = arbitration_prompt(EVIDENCE, lead, recall)
        self.assertIn("| Fumed Silica |", prompt)
        self.assertIn("official rheology", prompt)
        self.assertIn("行业通常使用", prompt)
        self.assertIn("绝不能用来新建精确产品", prompt)
        self.assertNotIn("- Andalusite", prompt)

    def test_runtime_memory_keeps_pac_and_high_purity_routes_enabled(self) -> None:
        memory = (PROJECT_DIR / "config" / "hermes" / "aceler-memory" / "MEMORY.md").read_text(encoding="utf-8")
        self.assertNotIn("CAC_PAC、CORE、CHAMOTTE资料状态为待完善", memory)
        self.assertIn("水处理 PAC/PACl 是已启用的独立目录路线", memory)
        self.assertIn("只有已证实的规格冲突才降低产品匹配", memory)

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
        self.assertFalse(_substantive_extract("正在确认你是不是机器人！请稍候，我们正在检查您的浏览器。" * 4))

    def test_substantive_extract_rejects_anubis_challenge(self) -> None:
        challenge = (
            "# Making sure you're not a bot!\n"
            "Anubis could not load its JavaScript. Anubis uses a Proof-of-Work scheme "
            "to protect this website from automated requests. " * 4
        )
        self.assertFalse(_substantive_extract(challenge))

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

    def test_json_parse_repairs_common_syntax_only(self) -> None:
        self.assertEqual(extract_json_object("{'company': 'Example',}"), {"company": "Example"})
        self.assertEqual(extract_json_object('{"company": "Example",}'), {"company": "Example"})
        self.assertEqual(
            extract_json_object('{"reason":"官网明确"manufactures refractories"，因此相关。"}'),
            {"reason": '官网明确"manufactures refractories"，因此相关。'},
        )

    def test_mock_valid_company_calls_hermes_once_and_publishes_valid(self) -> None:
        invocation = {"assessment": assessment(), "errors": [], "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", return_value=invocation) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(item["status"], "valid")
            self.assertEqual(item["validation"]["score"], 85)
            self.assertTrue((Path(item["record_dir"]) / "accepted-assessment.json").is_file())
            self.assertTrue((Path(item["record_dir"]) / "evidence-bundle.json").is_file())
            self.assertTrue((Path(item["record_dir"]) / "orchestration.json").is_file())
            self.assertEqual(item["research"]["orchestration_version"], "v1")
            self.assertEqual(item["research"]["role_call_counts"], {"lead": 1, "recall": 0, "arbiter": 0})
            self.assertFalse((Path(directory) / ("defer" + "red-companies.json")).exists())

    def test_simple_format_errors_are_repaired_without_another_hermes_call(self) -> None:
        malformed = assessment()
        malformed["sources"][0]["url"] = "https://invented.test/process"
        malformed["sources"][0]["source_type"] = "official"
        malformed["company_positioning"]["evidence_ids"] = []
        malformed["role_judgment"]["evidence_ids"] = []
        malformed["match"]["entry_barrier"] = "unknown"
        malformed["procurement_directions"][0]["product"] = "Refractory Ceramic Fiber"
        invocation = {
            "assessment": malformed,
            "errors": [],
            "raw": json.dumps(malformed),
            "usage": None,
            "attempt": {"kind": "research", "has_json": True},
            "seconds": 0.1,
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", return_value=invocation
        ) as mocked:
            item = research_one(
                record(),
                1,
                Path(directory),
                hermes=Path("/bin/true"),
                evidence_pack=EVIDENCE,
                max_attempts=1,
                review_zero_score=False,
            )
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 85)
        self.assertEqual(item["assessment"]["sources"][0]["url"], "https://example.test/process")
        self.assertEqual(item["assessment"]["match"]["entry_barrier"], "低")
        self.assertEqual(item["assessment"]["procurement_directions"], [])
        self.assertTrue(item["research"]["attempts"][0]["repairs"])

    def test_valid_zero_gets_one_review_and_accepts_a_valid_correction(self) -> None:
        invocations = [
            {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": assessment(), "errors": [], "raw": "corrected", "usage": None, "attempt": {"kind": "zero_score_review", "has_json": True}, "seconds": 0.1},
            {
                "assessment": {"decision": "recall", "reason": "S1 支持遗漏的直接路径。", "evidence_ids": ["S1"]},
                "errors": [],
                "raw": "arbiter",
                "usage": None,
                "attempt": {"kind": "arbiter", "has_json": True},
                "seconds": 0.1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 85)
        self.assertEqual(item["research"]["attempt_count"], 3)
        self.assertEqual(item["research"]["selected_role"], "recall")
        self.assertEqual(item["research"]["zero_score_review"]["initial_score"], 0)
        self.assertTrue(item["research"]["zero_score_review"]["accepted"])
        self.assertTrue(item["research"]["zero_score_review"]["changed_score"])
        self.assertIn("CRITIC_SCOPE", mocked.call_args_list[1].kwargs["prompt"])
        self.assertIn("上次已通过校验的 JSON", mocked.call_args_list[1].kwargs["prompt"])
        self.assertEqual(mocked.call_args_list[1].kwargs["raw_path"].name, "hermes-raw-recall-attempt-1.txt")
        self.assertEqual(item["research"]["arbitration"]["decision"], "recall")

    def test_valid_zero_review_can_keep_zero_without_repeating(self) -> None:
        invocation = {"assessment": zero_assessment(), "errors": [], "raw": "zero", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch("company_research_trial.company_research_trial._invoke_hermes", side_effect=[invocation, invocation]) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(item["status"], "valid")
        self.assertEqual(item["validation"]["score"], 0)
        self.assertFalse(item["research"]["zero_score_review"]["accepted"])
        self.assertFalse(item["research"]["zero_score_review"]["changed_score"])
        self.assertEqual(item["research"]["selected_role"], "lead")

    def test_relevant_supply_partner_below_middle_band_gets_semantic_review(self) -> None:
        low = assessment()
        low["role_judgment"]["operational_role"] = "分销商"
        low["role_judgment"]["commercial_relationship"] = "供应合作伙伴"
        low["match"]["follow_up"] = "淘汰"
        low["match"]["components"] = {
            "production_process_need": 6,
            "catalog_fit": 24,
            "consumption_intensity": 8,
            "demand_recurrence": 8,
            "company_role_fit": 6,
        }
        invocations = [
            {"assessment": low, "errors": [], "raw": "low", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": assessment(), "errors": [], "raw": "reviewed", "usage": None, "attempt": {"kind": "low_score_review", "has_json": True}, "seconds": 0.1},
            {
                "assessment": {"decision": "recall", "reason": "S1 支持遗漏的供应路径。", "evidence_ids": ["S1"]},
                "errors": [],
                "raw": "arbiter",
                "usage": None,
                "attempt": {"kind": "arbiter", "has_json": True},
                "seconds": 0.1,
            },
        ]
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ) as mocked:
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(item["validation"]["score"], 85)
        review = item["research"]["zero_score_review"]
        self.assertEqual(review["kind"], "low_consistency")
        self.assertEqual(review["initial_score"], 50)
        self.assertEqual(review["review_score"], 85)
        self.assertIn("与 Lead 分离的召回审查角色", mocked.call_args_list[1].kwargs["prompt"])
        self.assertEqual(mocked.call_args_list[1].kwargs["reasoning"], "high")
        self.assertEqual(mocked.call_count, 3)

    def test_low_score_review_is_a_recall_audit_and_cannot_reduce_a_valid_score(self) -> None:
        low = assessment()
        low["role_judgment"]["operational_role"] = "分销商"
        low["role_judgment"]["commercial_relationship"] = "供应合作伙伴"
        low["match"]["follow_up"] = "淘汰"
        low["match"]["components"] = {
            "production_process_need": 6,
            "catalog_fit": 24,
            "consumption_intensity": 8,
            "demand_recurrence": 8,
            "company_role_fit": 4,
        }
        lowered = copy.deepcopy(low)
        lowered["match"]["components"]["catalog_fit"] = 14
        prompt = low_score_review_prompt("BASE", low, 50)
        self.assertIn("不得降低", prompt)
        self.assertIn("保持上次", prompt)
        critic_prompt = recall_candidate_prompt("BASE", low, 50)
        self.assertIn("CRITIC_SCOPE", critic_prompt)
        self.assertIn("上次已通过校验的 JSON", critic_prompt)
        invocations = [
            {"assessment": low, "errors": [], "raw": "low", "usage": None, "attempt": {"kind": "research", "has_json": True}, "seconds": 0.1},
            {"assessment": lowered, "errors": [], "raw": "lowered", "usage": None, "attempt": {"kind": "low_score_review", "has_json": True}, "seconds": 0.1},
        ]
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial._invoke_hermes", side_effect=invocations
        ):
            item = research_one(record(), 1, Path(directory), hermes=Path("/bin/true"), evidence_pack=EVIDENCE)
        self.assertEqual(item["validation"]["score"], 50)
        review = item["research"]["zero_score_review"]
        self.assertFalse(review["accepted"])
        self.assertEqual(review["review_score"], 40)
        self.assertIn("lower", " ".join(review["errors"]).lower())

    def test_low_score_review_includes_confirmed_terminal_or_channel_routes(self) -> None:
        terminal = assessment()
        terminal["role_judgment"]["operational_role"] = "终端用户"
        terminal["role_judgment"]["commercial_relationship"] = "潜在客户"
        terminal["match"]["relevant_process_or_business_confirmed"] = False
        terminal["match"]["follow_up"] = "淘汰"
        self.assertTrue(_needs_low_score_review(terminal, 50))

        terminal["match"]["follow_up"] = "跟进"
        self.assertFalse(_needs_low_score_review(terminal, 50))

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
                prompt="re\x00search",
            )
        command = mocked.call_args.args[0]
        self.assertIn("--ignore-rules", command)
        self.assertEqual(command[command.index("--model") + 1], "MiniMax-M3")
        self.assertEqual(command[command.index("--provider") + 1], "minimax-cn")
        self.assertNotIn("--skills", command)  # Hermes v0.20.0 oneshot drops it; the contract is embedded in the prompt.
        self.assertNotIn("\x00", command[-1])
        self.assertEqual(command[-1], "research")

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

    def test_refresh_path_uses_recall_first_retrieval(self) -> None:
        invocation = {"assessment": assessment(), "errors": [], "raw": "valid", "usage": None, "attempt": {}, "seconds": 0.1}
        with tempfile.TemporaryDirectory() as directory, patch(
            "company_research_trial.company_research_trial.recall_first_anysearch_pack",
            return_value=(EVIDENCE, {"mode": "recall_recovery", "selected_urls": ["https://example.test/process"]}),
        ) as retrieval, patch(
            "company_research_trial.company_research_trial._invoke_hermes", return_value=invocation
        ):
            item = research_one(
                record(), 1, Path(directory), hermes=Path("/bin/true"), refresh_evidence_cache=True
            )
        self.assertEqual(item["status"], "valid")
        self.assertEqual(retrieval.call_count, 1)
        self.assertEqual(item["anysearch"]["mode"], "recall_recovery")

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
