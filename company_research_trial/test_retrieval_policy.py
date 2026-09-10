import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from . import company_research_trial as C
from . import retrieval_policy as P


ROW = {"id": "development", "name": "Development Works", "website": "https://example.test"}


def result(score=80, status="valid", identity="confirmed"):
    return {"status": status, "assessment": {"identity_status": identity, "match": {"follow_up": "跟进" if score >= 55 else "淘汰"}},
            "validation": {"valid": status == "valid", "score": score}}


class RetrievalPolicyTests(unittest.TestCase):
    def test_interrupted_confirmation_does_not_publish_deletable_candidate(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(P, "website_pack", return_value=("evidence", {})) as pack:
            run = Path(temporary)
            def researcher(record, index, run_dir, **kwargs):
                if "evidence_pack" not in kwargs:
                    raise C.AnySearchQuotaExhausted("quota during full confirmation")
                item = result(0)
                P.save(C._record_dir(record, index, run_dir) / "result.json", item)
                return item
            with self.assertRaises(C.AnySearchQuotaExhausted):
                P.research_with_policy(ROW, 1, run, mode="website_first", researcher=researcher)
            self.assertFalse((C._record_dir(ROW, 1, run) / "result.json").exists())
            with patch.object(C, "research_one", return_value=result(80)) as baseline:
                item = P.research_with_policy(ROW, 1, run, mode="website_first")
            baseline.assert_called_once()
            pack.assert_called_once()  # saved candidate reused after interruption
            self.assertEqual(item["validation"]["score"], 80)

    def test_negative_failed_and_uncertain_candidates_require_baseline(self):
        for candidate in (result(0), result(20), result(80, "failed"), result(80, identity="unresolved")):
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as temporary, patch.object(P, "website_pack", return_value=("evidence", {})):
                baseline = result(85)
                with patch.object(C, "research_one", side_effect=[candidate, baseline]) as research:
                    item = P.research_with_policy(ROW, 1, Path(temporary), mode="website_first")
                self.assertEqual(research.call_count, 2)
                self.assertEqual(item["validation"]["score"], 85)
                self.assertEqual(item["retrieval_policy"]["used"], "baseline_confirmation")

    def test_positive_skips_paid_baseline_but_audit_checks_it(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(P, "website_pack", return_value=("evidence", {})):
            with patch.object(C, "research_one", return_value=result()) as research:
                item = P.research_with_policy(ROW, 1, Path(temporary), mode="website_first")
                research.assert_called_once()
                self.assertEqual(item["retrieval_policy"]["used"], "website_first")
            with patch.object(C, "research_one", side_effect=[result(), result(0)]):
                item = P.research_with_policy(ROW, 2, Path(temporary), mode="website_first", audit=True)
                self.assertIn("quality_alert", item["retrieval_policy"])
                self.assertEqual(item["validation"]["score"], 0)

    def test_quota_never_falls_back_and_meter_is_saved(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(P, "website_pack", side_effect=C.AnySearchQuotaExhausted("quota")), patch.object(C, "research_one") as research:
            with self.assertRaises(C.AnySearchQuotaExhausted):
                P.research_with_policy(ROW, 1, Path(temporary), mode="website_first")
            research.assert_not_called()
            self.assertTrue((C._record_dir(ROW, 1, Path(temporary)) / "request-usage.json").exists())
            self.assertIsNone(C.ANYSEARCH_REQUEST_METER.get())

    def test_request_meter_counts_queries_and_failed_attempts(self):
        meter = {"search_requests": 0, "extract_requests": 0, "cli_attempts": 0}
        token = C.ANYSEARCH_REQUEST_METER.set(meter)
        try:
            with patch.object(C.subprocess, "run", side_effect=TimeoutError("timeout")):
                with self.assertRaises(TimeoutError):
                    C.run_anysearch_cli(["batch_search", "--query", "one", "--query", "two"])
            self.assertEqual(meter, {"search_requests": 2, "extract_requests": 0, "cli_attempts": 1})
        finally:
            C.ANYSEARCH_REQUEST_METER.reset(token)

    def test_direct_three_pages_need_no_search_and_stay_on_domain(self):
        text = "Confirmed business information " * 8
        homepage = text + " [Products](https://example.test/products) [Plant](https://example.test/applications) [Offsite](https://untrusted.test/products)"
        with patch.object(C, "_fallback_extract_output", side_effect=lambda url, timeout: homepage if url == ROW["website"] else text) as fetch, patch.object(C, "run_anysearch_cli") as search:
            pack, metadata = P.website_pack(ROW)
        search.assert_not_called()
        self.assertEqual(metadata["local_extract_calls"], 3)
        self.assertNotIn("untrusted.test", " ".join(call.args[0] for call in fetch.call_args_list))
        self.assertEqual(len(C._pack_urls(pack)), 3)


if __name__ == "__main__":
    unittest.main()
