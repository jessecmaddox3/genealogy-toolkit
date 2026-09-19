"""Working-confidence decisions for imported genealogy claims."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ConfidenceDecision:
    """The current working status of one assertion or relationship claim."""

    confidence: str
    rationale: str
    review_required: bool


def classify_initial_assertion(
    assertion: Mapping[str, object],
) -> ConfidenceDecision:
    """Classify explicit review signals without grading source documentation."""
    contradictions = assertion.get("contradictions", ())
    if contradictions:
        return ConfidenceDecision(
            "quarantined_contradiction",
            "An explicit contradiction accompanies this claim. Review signals: "
            + ", ".join(str(value) for value in contradictions) + ".",
            True,
        )
    if assertion.get("identity_ambiguity"):
        return ConfidenceDecision(
            "plausible_lead",
            "Identity ambiguity requires review before relying on this claim.",
            True,
        )
    return ConfidenceDecision(
        "accepted_working",
        "No explicit contradiction or identity ambiguity accompanies this claim.",
        False,
    )
