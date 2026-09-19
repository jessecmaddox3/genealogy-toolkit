"""Working-confidence policy tests."""

from genealogy.confidence import classify_initial_assertion


def test_tree_aggregate_defaults_to_accepted_working() -> None:
    """A coherent tree claim must remain usable in the working tree."""
    decision = classify_initial_assertion(
        {"source_tier": "tree_aggregate", "contradictions": []}
    )

    assert decision.confidence == "accepted_working"
    assert decision.review_required is False


def test_missing_citation_does_not_downgrade() -> None:
    """Citation count must not turn a coherent claim into a lower-confidence one."""
    decision = classify_initial_assertion(
        {
            "source_tier": "tree_aggregate",
            "citation_count": 0,
            "contradictions": [],
        }
    )

    assert decision.confidence == "accepted_working"


def test_impossible_parent_age_is_quarantined() -> None:
    """An explicit impossible-parent-age finding must stop reliance on the claim."""
    decision = classify_initial_assertion(
        {
            "source_tier": "tree_aggregate",
            "contradictions": ["parent_age_below_13"],
        }
    )

    assert decision.confidence == "quarantined_contradiction"
    assert decision.review_required is True


def test_ambiguous_identity_is_a_plausible_lead() -> None:
    """An identity problem requires review without asserting a contradiction."""
    decision = classify_initial_assertion(
        {"source_tier": "tree_aggregate", "identity_ambiguity": True}
    )

    assert decision.confidence == "plausible_lead"
    assert decision.review_required is True
