"""Deterministic orchestration for lead, recall, and arbitration roles."""

from __future__ import annotations

from typing import Any, Callable

from company_research_trial.agent_contracts import AgentCandidate, ArbitrationDecision, OrchestrationResult


def _decision_signature(assessment: dict[str, Any] | None) -> tuple[Any, ...]:
    assessment = assessment or {}
    match = assessment.get("match") or {}
    products = tuple(
        sorted(
            str(direction.get("product") or "")
            for direction in assessment.get("procurement_directions") or []
            if isinstance(direction, dict)
        )
    )
    return (
        match.get("product_match"),
        match.get("commercial_match"),
        match.get("follow_up"),
        products,
    )


def orchestrate_assessment(
    *,
    run_lead: Callable[[], AgentCandidate],
    should_run_recall: Callable[[dict[str, Any], int], bool],
    run_recall: Callable[[str, AgentCandidate], AgentCandidate],
    run_arbiter: Callable[[AgentCandidate, AgentCandidate], ArbitrationDecision],
    review_enabled: bool = True,
) -> OrchestrationResult:
    """Run the smallest role graph needed for one company's assessment."""
    lead = run_lead()
    attempts = list(lead.attempts)
    review = {
        "enabled": review_enabled,
        "triggered": False,
        "accepted": False,
        "changed_score": False,
        "initial_score": lead.score,
        "review_score": None,
        "errors": [],
        "kind": None,
        "selected_role": "lead",
    }
    if not lead.valid or not review_enabled or lead.score is None:
        return OrchestrationResult(lead, tuple(attempts), review, None)

    kind = "zero" if lead.score == 0 else "low_consistency"
    if not should_run_recall(lead.assessment or {}, lead.score):
        return OrchestrationResult(lead, tuple(attempts), review, None)

    review.update({"triggered": True, "kind": kind})
    try:
        recall = run_recall(kind, lead)
    except Exception as exc:
        review["errors"] = [f"Recall role failed unexpectedly: {type(exc).__name__}"]
        return OrchestrationResult(lead, tuple(attempts), review, None)
    attempts.extend(recall.attempts)
    review["review_score"] = recall.score
    if not recall.valid:
        review["errors"] = list(recall.errors)
        return OrchestrationResult(lead, tuple(attempts), review, None)
    if recall.score is None or recall.score < lead.score:
        review["errors"] = ["Recall candidate cannot lower the first valid score"]
        return OrchestrationResult(lead, tuple(attempts), review, None)
    if recall.score == lead.score and _decision_signature(recall.assessment) == _decision_signature(lead.assessment):
        return OrchestrationResult(lead, tuple(attempts), review, None)

    try:
        arbitration = run_arbiter(lead, recall)
    except Exception as exc:
        review["errors"] = [f"Arbiter failed unexpectedly: {type(exc).__name__}"]
        return OrchestrationResult(lead, tuple(attempts), review, None)
    arbiter_attempt = arbitration.invocation.get("attempt")
    if isinstance(arbiter_attempt, dict):
        attempts.append({**arbiter_attempt, "number": len(attempts) + 1, "errors": list(arbitration.errors)})
    if not arbitration.valid:
        review["errors"] = list(arbitration.errors)
        return OrchestrationResult(lead, tuple(attempts), review, arbitration)
    if arbitration.decision != "recall":
        return OrchestrationResult(lead, tuple(attempts), review, arbitration)

    review.update(
        {
            "accepted": True,
            "changed_score": recall.score != lead.score,
            "selected_role": "recall",
        }
    )
    return OrchestrationResult(recall, tuple(attempts), review, arbitration)
