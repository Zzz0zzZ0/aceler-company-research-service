import unittest

from company_research_trial.structured_evidence import extraction_prompt, prepare_structured_evidence


RAW = """# Evidence

## S1
URL: https://example.test/process
Title: Process

The company manufactures refractory [castables](https://example.test/products) and installs furnace linings.
"""


class StructuredEvidenceTests(unittest.TestCase):
    def test_extractor_requires_short_contiguous_quotes_for_portfolio_facts(self):
        prompt = extraction_prompt("Example", RAW)
        self.assertIn("single contiguous substring", prompt)
        self.assertIn("separate short quotations", prompt)
        self.assertIn("Do not join non-adjacent list items", prompt)

    def test_extractor_resolves_related_entity_context_without_an_exact_wording_gate(self):
        prompt = extraction_prompt("SARRALLE SERVICIOS GENERALES S.L.", RAW)
        self.assertIn("Resolve entity scope from the complete source context", prompt)
        self.assertIn("plausible operating relationship", prompt)
        self.assertIn("mark identity_status ambiguous", prompt)
        self.assertIn("clearly different namesake or unrelated entity", prompt)

    def test_verified_overlay_keeps_raw_evidence_for_semantic_scoring(self):
        result = prepare_structured_evidence(
            {
                "company": "Example",
                "identity_status": "confirmed",
                "core_business_confirmed": True,
                "facts": [
                    {
                        "category": "open category",
                        "statement": "The company manufactures castables and installs linings.",
                        "evidence": [{"source_id": "S1", "quote": "manufactures refractory castables and installs furnace linings"}],
                    },
                    {
                        "category": "invented",
                        "statement": "The company operates an EAF.",
                        "evidence": [{"source_id": "S1", "quote": "operates an EAF"}],
                    },
                ],
                "unresolved": ["Purchasing route is unknown"],
            },
            RAW,
        )
        self.assertEqual(result["status"], "usable")
        self.assertEqual(len(result["facts"]), 1)
        self.assertIn("open category", result["evidence_pack"])
        self.assertNotIn("operates an EAF", result["evidence_pack"])
        self.assertIn("Original evidence for semantic assessment", result["evidence_pack"])
        self.assertIn("manufactures refractory [castables]", result["evidence_pack"])

    def test_failed_quote_extraction_does_not_block_semantic_scoring(self):
        result = prepare_structured_evidence(
            {
                "company": "Example",
                "identity_status": "confirmed",
                "core_business_confirmed": True,
                "facts": [
                    {
                        "category": "positioning",
                        "statement": "The company makes refractory products.",
                        "evidence": [{"source_id": "S1", "quote": "not present in the source"}],
                    }
                ],
                "unresolved": ["Exact purchasing route is unpublished"],
            },
            RAW,
        )
        self.assertEqual(result["status"], "usable")
        self.assertEqual(result["facts"], [])
        self.assertIn("audit aid, not a scoring eligibility gate", result["evidence_pack"])
        self.assertIn("manufactures refractory [castables]", result["evidence_pack"])

    def test_ambiguous_identity_is_context_not_a_programmatic_gate(self):
        result = prepare_structured_evidence(
            {
                "company": "Example International",
                "identity_status": "ambiguous",
                "core_business_confirmed": True,
                "facts": [
                    {
                        "category": "legal relationship",
                        "statement": "The named company shares an operating brand with a related entity.",
                        "evidence": [{"source_id": "S1", "quote": "manufactures refractory castables and installs furnace linings"}],
                    }
                ],
                "unresolved": ["The exact legal relationship is not stated"],
            },
            RAW,
        )
        self.assertEqual(result["status"], "usable")
        self.assertIn("advisory", result["evidence_pack"])
        self.assertIn("not a scoring gate", result["evidence_pack"])
        self.assertIn("resolve identity semantically", result["evidence_pack"])
        self.assertNotIn("entity attribution is binding", result["evidence_pack"])


if __name__ == "__main__":
    unittest.main()
