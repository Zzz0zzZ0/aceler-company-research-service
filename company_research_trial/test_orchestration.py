from __future__ import annotations

import unittest

from company_research_trial.agent_contracts import AgentCandidate, ArbitrationDecision
from company_research_trial.orchestration import orchestrate_assessment


def candidate(role: str, score: int, *, product: str = "", valid: bool = True) -> AgentCandidate:
    assessment = {
        "match": {
            "product_match": score // 10,
            "commercial_match": score // 10,
            "follow_up": "跟进" if score >= 55 else "淘汰",
        },
        "procurement_directions": [{"product": product}] if product else [],
    }
    return AgentCandidate(
        role=role,
        assessment=assessment,
        validation={"valid": valid, "score": score},
        invocation={"attempt": {"kind": role}},
        attempts=({"kind": role, "number": 1},),
        errors=() if valid else ("invalid candidate",),
    )


def arbitrate(decision: str | None, errors: tuple[str, ...] = ()) -> ArbitrationDecision:
    return ArbitrationDecision(
        decision=decision,
        reason="supported",
        evidence_ids=("S1",),
        invocation={"attempt": {"kind": "arbiter"}},
        errors=errors,
    )


class OrchestrationTests(unittest.TestCase):
    def test_high_score_uses_only_lead(self) -> None:
        calls: list[str] = []
        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 70),
            should_run_recall=lambda _assessment, _score: False,
            run_recall=lambda _kind, _lead: calls.append("recall"),  # type: ignore[arg-type,return-value]
            run_arbiter=lambda _lead, _recall: calls.append("arbiter"),  # type: ignore[arg-type,return-value]
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertFalse(result.review["triggered"])
        self.assertEqual(calls, [])

    def test_higher_recall_candidate_requires_arbiter(self) -> None:
        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 40),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 65, product="Silicon Carbide"),
            run_arbiter=lambda _lead, _recall: arbitrate("recall"),
        )
        self.assertEqual(result.selected.role, "recall")
        self.assertTrue(result.review["accepted"])
        self.assertTrue(result.review["changed_score"])
        self.assertEqual(len(result.attempts), 3)

    def test_invalid_arbiter_falls_back_to_lead(self) -> None:
        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 0),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 60, product="Calcium Aluminate Cement & PAC"),
            run_arbiter=lambda _lead, _recall: arbitrate(None, ("bad decision",)),
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertEqual(result.review["errors"], ["bad decision"])

    def test_lower_recall_candidate_is_rejected_without_arbitration(self) -> None:
        called = False

        def arbiter(_lead: AgentCandidate, _recall: AgentCandidate) -> ArbitrationDecision:
            nonlocal called
            called = True
            return arbitrate("recall")

        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 45),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 35),
            run_arbiter=arbiter,
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertFalse(called)
        self.assertIn("cannot lower", result.review["errors"][0])

    def test_same_decision_does_not_spend_an_arbiter_call(self) -> None:
        called = False

        def arbiter(_lead: AgentCandidate, _recall: AgentCandidate) -> ArbitrationDecision:
            nonlocal called
            called = True
            return arbitrate("lead")

        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 0),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 0),
            run_arbiter=arbiter,
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertFalse(called)

    def test_review_can_be_disabled_for_rollback(self) -> None:
        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 0),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 70),
            run_arbiter=lambda _lead, _recall: arbitrate("recall"),
            review_enabled=False,
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertFalse(result.review["triggered"])

    def test_recall_exception_keeps_valid_lead(self) -> None:
        def fail_recall(_kind: str, _lead: AgentCandidate) -> AgentCandidate:
            raise TimeoutError("provider detail must not leak")

        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 40),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=fail_recall,
            run_arbiter=lambda _lead, _recall: arbitrate("recall"),
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertEqual(result.review["errors"], ["Recall role failed unexpectedly: TimeoutError"])
        self.assertNotIn("provider detail", result.review["errors"][0])

    def test_arbiter_exception_keeps_valid_lead(self) -> None:
        def fail_arbiter(_lead: AgentCandidate, _recall: AgentCandidate) -> ArbitrationDecision:
            raise OSError("filesystem detail must not leak")

        result = orchestrate_assessment(
            run_lead=lambda: candidate("lead", 40),
            should_run_recall=lambda _assessment, _score: True,
            run_recall=lambda _kind, _lead: candidate("recall", 60, product="Silicon Carbide"),
            run_arbiter=fail_arbiter,
        )
        self.assertEqual(result.selected.role, "lead")
        self.assertEqual(result.review["errors"], ["Arbiter failed unexpectedly: OSError"])
        self.assertNotIn("filesystem detail", result.review["errors"][0])


if __name__ == "__main__":
    unittest.main()
