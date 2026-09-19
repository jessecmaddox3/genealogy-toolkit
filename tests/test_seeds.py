"""Private seed validation and canonical ingestion tests."""

import json
from pathlib import Path

import pytest

from genealogy.rm_reader import extract_snapshot
from genealogy.seeds import (
    SeedValidationError,
    ingest_private_seed,
    load_private_seed,
)
from genealogy.store import create_store, ingest_snapshot
from tests.fixtures.rm_fixture import build_rm_fixture


def _write_seed(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_seed_rejects_duplicate_seed_ids(tmp_path: Path) -> None:
    """Dropping duplicate detection would make relationship endpoints ambiguous."""
    path = tmp_path / "seed.json"
    path.write_text(
        '{"people":[{"seed_id":"x","display_name":"A","living":true},'
        '{"seed_id":"x","display_name":"B","living":true}],"relationships":[]}',
        encoding="utf-8",
    )

    with pytest.raises(SeedValidationError, match="duplicate seed_id x"):
        load_private_seed(path)


def test_seed_rejects_relationship_to_unknown_person(tmp_path: Path) -> None:
    """Accepting an unknown endpoint would create an orphaned private bridge."""
    path = tmp_path / "seed.json"
    path.write_text(
        '{"people":[{"seed_id":"x","display_name":"A","living":true}],'
        '"relationships":[{"parent":"missing","child":"x"}]}',
        encoding="utf-8",
    )

    with pytest.raises(SeedValidationError, match="missing"):
        load_private_seed(path)


def test_seed_rejects_familysearch_id_for_living_person(tmp_path: Path) -> None:
    """A public identifier on a living seed person would weaken the privacy boundary."""
    path = _write_seed(
        tmp_path / "seed.json",
        {
            "people": [
                {
                    "seed_id": "living",
                    "display_name": "Private",
                    "living": True,
                    "familysearch_id": "AAAA-111",
                }
            ],
            "relationships": [],
        },
    )

    with pytest.raises(SeedValidationError, match=r"living.*FamilySearch"):
        load_private_seed(path)


def test_ingest_seed_reuses_only_exact_familysearch_identity(
    tmp_path: Path,
) -> None:
    """Dropping exact-ID precedence or adding name matching breaks identity."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = extract_snapshot(
        build_rm_fixture(tmp_path / "fixture.rmtree"),
        "fixture-001",
    )
    ingest_snapshot(connection, snapshot, "fixture-hash")
    imported_anchor_id = connection.execute(
        """
        SELECT person_id
        FROM person_identifier
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        """
    ).fetchone()[0]
    seed = load_private_seed(
        _write_seed(
            tmp_path / "seed.json",
            {
                "people": [
                    {
                        "seed_id": "anchor",
                        "display_name": "Deliberately Different Name",
                        "living": False,
                        "familysearch_id": "AAAA-111",
                    },
                    {
                        "seed_id": "lookalike",
                        "display_name": "Parent One Example",
                        "living": False,
                        "familysearch_id": None,
                    },
                    {
                        "seed_id": "private-child",
                        "display_name": "Private Child",
                        "living": True,
                        "familysearch_id": None,
                    },
                ],
                "relationships": [
                    {"parent": "anchor", "child": "private-child"}
                ],
            },
        )
    )

    ingest_private_seed(connection, seed)

    seed_people = dict(
        connection.execute(
            """
            SELECT value, person_id
            FROM person_identifier
            WHERE system = 'private_seed'
            """
        ).fetchall()
    )
    assert seed_people["anchor"] == imported_anchor_id
    assert seed_people["lookalike"] != imported_anchor_id
    assert connection.execute("SELECT count(*) FROM person").fetchone()[0] == 5
    assert connection.execute(
        """
        SELECT value_text, is_private
        FROM assertion
        WHERE snapshot_id LIKE 'private-seed-%'
          AND predicate = 'person.primary_name'
        ORDER BY value_text
        """
    ).fetchall() == [
        ("Deliberately Different Name", 1),
        ("Parent One Example", 1),
        ("Private Child", 1),
    ]
    assert connection.execute(
        """
        SELECT ra.subject_person_id, ra.object_person_id, c.confidence
        FROM relationship_assertion AS ra
        JOIN conclusion AS c
          ON c.chosen_relationship_assertion_id = ra.relationship_assertion_id
        WHERE ra.snapshot_id LIKE 'private-seed-%'
        """
    ).fetchone() == (
        imported_anchor_id,
        seed_people["private-child"],
        "accepted_working",
    )

    counts_before_repeat = tuple(
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "snapshot",
            "person",
            "person_identifier",
            "assertion",
            "relationship_assertion",
            "conclusion",
        )
    )
    ingest_private_seed(connection, seed)
    counts_after_repeat = tuple(
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "snapshot",
            "person",
            "person_identifier",
            "assertion",
            "relationship_assertion",
            "conclusion",
        )
    )
    assert counts_after_repeat == counts_before_repeat


def test_ingest_seed_preserves_conflicting_identifier_error(
    tmp_path: Path,
) -> None:
    """Changing exact-ID resolution must retain the private-seed error contract."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES ('existing', 'existing', 'test', 0, 0, 0, 0, 0)
        """
    )
    for person_id in ("seed-person", "familysearch-person"):
        connection.execute(
            "INSERT INTO person(person_id, living, private) VALUES (?, 0, 0)",
            (person_id,),
        )
    connection.execute(
        """
        INSERT INTO person_identifier(
            person_id, system, value, scope_snapshot_id,
            first_seen_snapshot_id, last_seen_snapshot_id
        ) VALUES ('seed-person', 'private_seed', 'anchor', NULL, 'existing', 'existing')
        """
    )
    connection.execute(
        """
        INSERT INTO person_identifier(
            person_id, system, value, scope_snapshot_id,
            first_seen_snapshot_id, last_seen_snapshot_id
        ) VALUES (
            'familysearch-person', 'familysearch', 'AAAA-111', NULL,
            'existing', 'existing'
        )
        """
    )
    seed = load_private_seed(
        _write_seed(
            tmp_path / "seed.json",
            {
                "people": [
                    {
                        "seed_id": "anchor",
                        "display_name": "Anchor",
                        "living": False,
                        "familysearch_id": "AAAA-111",
                    }
                ],
                "relationships": [],
            },
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "seed_id anchor and FamilySearch ID AAAA-111 "
            "resolve to different canonical people"
        ),
    ):
        ingest_private_seed(connection, seed)
