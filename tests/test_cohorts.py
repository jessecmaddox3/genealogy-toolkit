"""Deterministic Root-centered cohort tests."""

import json
from pathlib import Path
import sqlite3

from genealogy.cohorts import recompute_cohorts
from genealogy.seeds import ingest_private_seed, load_private_seed
from genealogy.store import create_store


def _build_graph(tmp_path: Path) -> tuple[sqlite3.Connection, dict[str, str]]:
    connection = create_store(tmp_path / "genealogy.sqlite")
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "people": [
                    {"seed_id": seed_id, "display_name": seed_id, "living": False}
                    for seed_id in (
                        "root-subject",
                        "father",
                        "mother",
                        "paternal-grandfather",
                        "paternal-grandmother",
                        "maternal-grandfather",
                        "maternal-grandmother",
                        "aunt",
                        "aunt-spouse",
                        "paternal-other-partner",
                        "half-uncle",
                        "half-uncle-spouse",
                        "single-parent-child",
                        "single-parent-child-spouse",
                        "witness",
                        "unrelated",
                    )
                ],
                "relationships": [
                    {"parent": "father", "child": "root-subject"},
                    {"parent": "mother", "child": "root-subject"},
                    {"parent": "paternal-grandfather", "child": "father"},
                    {"parent": "paternal-grandmother", "child": "father"},
                    {"parent": "paternal-grandfather", "child": "aunt"},
                    {"parent": "paternal-grandmother", "child": "aunt"},
                    {"parent": "maternal-grandfather", "child": "mother"},
                    {"parent": "maternal-grandmother", "child": "mother"},
                    {
                        "parent": "paternal-grandfather",
                        "child": "half-uncle",
                    },
                    {
                        "parent": "paternal-other-partner",
                        "child": "half-uncle",
                    },
                    {
                        "parent": "maternal-grandfather",
                        "child": "single-parent-child",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    ingest_private_seed(connection, load_private_seed(seed_path))
    people = dict(
        connection.execute(
            """
            SELECT value, person_id
            FROM person_identifier
            WHERE system = 'private_seed'
            """
        ).fetchall()
    )
    source_id, snapshot_id = connection.execute(
        """
        SELECT source_id, snapshot_id
        FROM source
        WHERE source_type = 'private_seed'
        """
    ).fetchone()

    for left, right, family in (
        ("father", "mother", "parents"),
        ("paternal-grandfather", "paternal-grandmother", "paternal"),
        ("maternal-grandfather", "maternal-grandmother", "maternal"),
        ("aunt", "aunt-spouse", "aunt"),
        ("half-uncle", "half-uncle-spouse", "half-uncle"),
        (
            "single-parent-child",
            "single-parent-child-spouse",
            "single-parent-child",
        ),
    ):
        _add_relationship(
            connection,
            subject_person_id=people[left],
            predicate="spouse",
            object_person_id=people[right],
            confidence="accepted_working",
            source_id=source_id,
            snapshot_id=snapshot_id,
            raw_id=f"spouse:{family}",
            family_id=family,
        )

    _add_relationship(
        connection,
        subject_person_id=people["unrelated"],
        predicate="parent_child",
        object_person_id=people["root-subject"],
        confidence="plausible_lead",
        source_id=source_id,
        snapshot_id=snapshot_id,
        raw_id="plausible-parent",
        family_id="plausible",
    )

    connection.execute(
        """
        INSERT INTO cohort_membership(
            person_id, cohort_code, inclusion_reason, derivation_method
        ) VALUES (?, 'D', 'Named witness in a family record', 'curated')
        """,
        (people["witness"],),
    )
    for person_id, code, reason, method in (
        (people["unrelated"], "A", "stale ancestor", "computed"),
        (people["witness"], "C", "stale spouse", "computed"),
        (people["father"], "Z", "stale background", "background"),
    ):
        connection.execute(
            """
            INSERT INTO cohort_membership(
                person_id, cohort_code, inclusion_reason, derivation_method
            ) VALUES (?, ?, ?, ?)
            """,
            (person_id, code, reason, method),
        )

    return connection, people


def _add_relationship(
    connection: sqlite3.Connection,
    *,
    subject_person_id: str,
    predicate: str,
    object_person_id: str,
    confidence: str,
    source_id: int,
    snapshot_id: str,
    raw_id: str,
    family_id: str,
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO relationship_assertion(
            subject_person_id, predicate, object_person_id, role,
            snapshot_id, source_id, raw_external_relationship_id,
            raw_external_family_id
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            subject_person_id,
            predicate,
            object_person_id,
            snapshot_id,
            source_id,
            raw_id,
            family_id,
        ),
    )
    relationship_id = cursor.lastrowid
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES ('relationship', ?, ?, ?, ?, 'test conclusion')
        """,
        (
            str(relationship_id),
            predicate,
            relationship_id,
            confidence,
        ),
    )


def test_recompute_cohorts_uses_current_accepted_graph_and_preserves_curated_d(
    tmp_path: Path,
) -> None:
    """Using raw or stale edges, including Researcher in A, or replacing D must fail."""
    connection, people = _build_graph(tmp_path)
    expected = {
        "A": tuple(
            sorted(
                people[seed_id]
                for seed_id in (
                    "father",
                    "mother",
                    "paternal-grandfather",
                    "paternal-grandmother",
                    "maternal-grandfather",
                    "maternal-grandmother",
                )
            )
        ),
        "B": tuple(
            sorted(
                people[seed_id]
                for seed_id in ("root-subject", "father", "mother", "aunt")
            )
        ),
        "C": (people["aunt-spouse"],),
        "D": (people["witness"],),
        "Z": tuple(
            sorted(
                people[seed_id]
                for seed_id in (
                    "unrelated",
                    "paternal-other-partner",
                    "half-uncle",
                    "half-uncle-spouse",
                    "single-parent-child",
                    "single-parent-child-spouse",
                )
            )
        ),
    }

    first = recompute_cohorts(connection, people["root-subject"])

    assert first.root_person_id == people["root-subject"]
    assert first.memberships == expected
    assert people["root-subject"] not in first.memberships["A"]
    assert connection.execute(
        """
        SELECT inclusion_reason, derivation_method
        FROM cohort_membership
        WHERE person_id = ? AND cohort_code = 'D'
        """,
        (people["witness"],),
    ).fetchone() == ("Named witness in a family record", "curated")
    assert connection.execute(
        """
        SELECT person_id, cohort_code
        FROM cohort_membership
        ORDER BY cohort_code, person_id
        """
    ).fetchall() == [
        (person_id, cohort)
        for cohort, person_ids in expected.items()
        for person_id in person_ids
    ]

    second = recompute_cohorts(connection, people["root-subject"])

    assert second == first
    assert connection.execute(
        """
        SELECT person_id, cohort_code
        FROM cohort_membership
        ORDER BY cohort_code, person_id
        """
    ).fetchall() == [
        (person_id, cohort)
        for cohort, person_ids in expected.items()
        for person_id in person_ids
    ]
