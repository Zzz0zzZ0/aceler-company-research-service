"""Small data contracts shared by the company-research orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceBundle:
    """Immutable evidence handed to every semantic role in one run."""

    company: str
    text: str
    sources: tuple[dict[str, str], ...]
    retrieval: dict[str, Any]
    sha256: str

    def manifest(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "sha256": self.sha256,
            "sources": list(self.sources),
            "source_count": len(self.sources),
            "retrieval": self.retrieval,
        }


@dataclass(frozen=True)
class AgentCandidate:
    """One validated full assessment produced by a semantic agent role."""

    role: str
    assessment: dict[str, Any] | None
    validation: dict[str, Any]
    invocation: dict[str, Any]
    attempts: tuple[dict[str, Any], ...]
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return isinstance(self.assessment, dict) and self.validation.get("valid") is True and not self.errors

    @property
    def score(self) -> int | None:
        value = self.validation.get("score")
        return value if isinstance(value, int) else None


@dataclass(frozen=True)
class ArbitrationDecision:
    """A bounded choice between the lead and recall candidates."""

    decision: str | None
    reason: str
    evidence_ids: tuple[str, ...]
    invocation: dict[str, Any]
    errors: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.decision in {"lead", "recall"} and not self.errors


@dataclass(frozen=True)
class OrchestrationResult:
    """Selected candidate plus an auditable trace of the role decisions."""

    selected: AgentCandidate
    attempts: tuple[dict[str, Any], ...]
    review: dict[str, Any]
    arbitration: ArbitrationDecision | None
