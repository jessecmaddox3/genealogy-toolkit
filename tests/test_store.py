"""Canonical genealogy store behavior and integrity tests."""

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from genealogy.records import RawIdentifier
from genealogy.rm_dates import parse_rm_date
from genealogy.rm_reader import extract_snapshot
from genealogy.store import (
    SnapshotConflictError,
    SnapshotIdentityConflictError,
    create_store,
    ingest_snapshot,
)
from tests.fixtures.rm_fixture import build_rm_fixture


REQUIRED_TABLES = {
    "snapshot",
    "person",
    "person_identifier",
    "person_identifier_observation",
    "person_observation",
    "event_observation",
    "source",
    "assertion",
    "relationship_assertion",
    "conclusion",
    "place",
    "cohort_membership",
    "research_question",
}

REQUIRED_INDEXES = {
    "idx_assertion_subject",
    "idx_assertion_predicate",
    "idx_assertion_source",
    "idx_person_identifier_external",
    "idx_person_identifier_observation_external",
    "idx_person_observation_sex",
    "idx_event_observation_person",
    "idx_relationship_subject",
    "idx_relationship_object",
}


def _fixture_snapshot(tmp_path: Path, snapshot_id: str = "fixture-001"):
    return extract_snapshot(
        build_rm_fixture(tmp_path / f"{snapshot_id}.rmtree"),
        snapshot_id,
    )


def test_create_store_has_complete_schema_and_required_indexes(
    tmp_path: Path,
) -> None:
    """Omitting a canonical table or query index must break the schema contract."""
    connection = create_store(tmp_path / "genealogy.sqlite")

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }

    assert REQUIRED_TABLES <= tables
    assert REQUIRED_INDEXES <= indexes


def test_create_store_enables_and_enforces_foreign_keys(tmp_path: Path) -> None:
    """Disabling SQLite foreign keys would allow orphaned canonical records."""
    connection = create_store(tmp_path / "genealogy.sqlite")

    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute(
            """
            INSERT INTO person_identifier(
                person_id, system, value, scope_snapshot_id,
                first_seen_snapshot_id, last_seen_snapshot_id
            ) VALUES ('missing', 'familysearch', 'AAAA-111', NULL, 'missing', 'missing')
            """
        )


def test_ingest_snapshot_preserves_assertions_relationships_and_raw_provenance(
    tmp_path: Path,
) -> None:
    """Dropping raw IDs, raw values, places, or ParentID must fail ingestion QA."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)

    result = ingest_snapshot(connection, snapshot, "abc123")

    assert result.snapshot_id == "fixture-001"
    assert result.people_added == 3
    assert result.assertions_added == 8
    assert result.relationships_added == 3
    assert connection.execute("SELECT count(*) FROM place").fetchone()[0] == 1
    assert connection.execute(
        """
        SELECT raw_value, parsed_value, raw_external_assertion_id,
               raw_external_owner_id, raw_external_place_id
        FROM assertion
        WHERE predicate = 'event.birth' AND raw_external_assertion_id = '1'
        """
    ).fetchone() == (
        "D.+19000102..+00000000..",
        '{"end":null,"modifier":"exact","parse_status":"parsed","start":{"day":2,"month":1,"year":1900}}',
        "1",
        "1",
        "1",
    )
    assert connection.execute(
        """
        SELECT value_text, raw_external_assertion_id
        FROM assertion
        WHERE predicate = 'rootsmagic.selected_parent_family'
        """
    ).fetchone() == ("1", "3")
    assert connection.execute(
        """
        SELECT predicate, role, raw_external_relationship_id,
               raw_external_family_id, raw_external_child_link_id
        FROM relationship_assertion
        ORDER BY relationship_assertion_id
        """
    ).fetchall() == [
        ("parent_child", "father", "child_link:1", "1", "1"),
        ("parent_child", "mother", "child_link:1", "1", "1"),
        ("spouse", None, "family:1", "1", None),
    ]
    assert connection.execute(
        """
        SELECT snapshot_id, external_person_id, primary_name_id, primary_name,
               surname, given_name, suffix, sex, living, private,
               source_parent_family_id,
               primary_name_assertion_id IS NOT NULL,
               selected_parent_assertion_id IS NOT NULL
        FROM person_observation
        WHERE external_person_id = '3'
        """
    ).fetchone() == (
        "fixture-001",
        "3",
        "3",
        "Child Example",
        "Example",
        "Child",
        "",
        0,
        1,
        1,
        "1",
        1,
        1,
    )
    assert connection.execute(
        """
        SELECT snapshot_id, external_event_id, owner_type, external_owner_id,
               external_family_id, fact_type_id, fact_type_name, raw_date,
               date_modifier, date_start_year, date_start_month, date_start_day,
               date_end_year, date_end_month, date_end_day, date_parse_status,
               external_place_id, raw_place_name, details, note, private,
               assertion_id IS NOT NULL, person_id IS NOT NULL
        FROM event_observation
        WHERE external_event_id = '1'
        """
    ).fetchone() == (
        "fixture-001",
        "1",
        0,
        "1",
        None,
        "1",
        "Birth",
        "D.+19000102..+00000000..",
        "exact",
        1900,
        1,
        2,
        None,
        None,
        None,
        "parsed",
        "1",
        "Larkhaven, Mistvale, Fictional Republic",
        "Imported detail",
        "Imported note",
        0,
        1,
        1,
    )


def test_ingestion_creates_accepted_working_conclusions_for_all_claim_types(
    tmp_path: Path,
) -> None:
    """Missing citations must not prevent imported claims from being usable."""
    connection = create_store(tmp_path / "genealogy.sqlite")

    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    assert connection.execute(
        "SELECT count(*) FROM conclusion"
    ).fetchone()[0] == 11
    assert connection.execute(
        """
        SELECT count(*)
        FROM conclusion
        WHERE confidence = 'accepted_working'
        """
    ).fetchone()[0] == 11
    assert connection.execute(
        """
        SELECT confidence
        FROM conclusion AS conclusion
        JOIN assertion AS assertion
          ON assertion.assertion_id = conclusion.chosen_assertion_id
        JOIN place AS place ON place.place_id = assertion.place_id
        WHERE assertion.predicate = 'place.raw_text'
        """
    ).fetchone() == ("accepted_working",)


def test_confidence_annotations_scope_identity_ambiguity_to_claims(
    tmp_path: Path,
) -> None:
    """An ambiguity annotation must not downgrade neighboring imported claims."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    annotations = {
        ("name", "1", "1"): {"identity_ambiguity": True},
        ("event", "1"): {"identity_ambiguity": True},
        ("place", "1"): {"identity_ambiguity": True},
        (
            "relationship",
            "parent_child",
            "1",
            "3",
            "father",
            "child_link:1",
        ): {"identity_ambiguity": True},
    }

    ingest_snapshot(
        connection,
        snapshot,
        "abc123",
        confidence_annotations=annotations,
    )

    assert connection.execute(
        """
        SELECT count(*)
        FROM conclusion
        WHERE confidence = 'plausible_lead'
          AND rationale LIKE 'Identity ambiguity%'
        """
    ).fetchone()[0] == 4
    assert connection.execute(
        """
        SELECT count(*)
        FROM conclusion
        WHERE confidence = 'accepted_working'
        """
    ).fetchone()[0] == 7
    changes_before_replay = connection.total_changes

    replay = ingest_snapshot(
        connection,
        snapshot,
        "abc123",
        confidence_annotations=annotations,
    )

    assert replay.assertions_added == 0
    assert replay.relationships_added == 0
    assert connection.total_changes == changes_before_replay


def test_parent_age_review_quarantines_only_the_parent_edge(tmp_path: Path) -> None:
    """Wholly invented age warning: individual observations stay available."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    people = tuple(replace(person, primary_name=name, surname="Fable", given=name.split()[0])
                   for person, name in zip(snapshot.people, ("Lumen Fable", "Tavi Fable", "Echo Fable")))
    dates = ("D.+18670809..+00000000..", "D.+18540311..+00000000..", "D.+18770912..+00000000..")
    events = tuple(replace(event, raw_date=raw, date=parse_rm_date(raw))
                   for event, raw in zip(snapshot.events, dates))
    ingest_snapshot(connection, replace(snapshot, people=people, events=events), "invented-age-review")
    assert connection.execute("""
        SELECT c.confidence FROM conclusion c JOIN relationship_assertion r
          ON r.relationship_assertion_id = c.chosen_relationship_assertion_id
        WHERE r.raw_external_relationship_id = 'child_link:1' AND r.role = 'father'
    """).fetchone() == ("quarantined_contradiction",)
    assert connection.execute("""
        SELECT count(*) FROM conclusion c JOIN assertion a ON a.assertion_id = c.chosen_assertion_id
        WHERE a.predicate IN ('person.primary_name', 'event.birth') AND c.confidence = 'accepted_working'
    """).fetchone()[0] == 6
    assert connection.execute("SELECT count(*) FROM conclusion WHERE confidence = 'quarantined_contradiction'").fetchone()[0] == 1


def test_ingest_same_snapshot_twice_is_an_exact_no_op(tmp_path: Path) -> None:
    """Replaying an immutable input must not duplicate or rewrite canonical rows."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    first = ingest_snapshot(connection, snapshot, "abc123")
    changes_before_repeat = connection.total_changes

    second = ingest_snapshot(connection, snapshot, "abc123")

    assert first.people_added == 3
    assert second.people_added == 0
    assert second.assertions_added == 0
    assert second.relationships_added == 0
    assert connection.total_changes == changes_before_repeat
    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM assertion").fetchone()[0] == 8
    assert connection.execute(
        "SELECT count(*) FROM person_observation"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM event_observation"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM person_identifier_observation"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM relationship_assertion"
    ).fetchone()[0] == 3


def test_snapshot_id_cannot_be_reused_with_a_different_manifest(
    tmp_path: Path,
) -> None:
    """Allowing a manifest hash change would destroy snapshot immutability."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    ingest_snapshot(connection, snapshot, "abc123")
    counts_before = tuple(
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("snapshot", "person", "assertion", "relationship_assertion")
    )

    with pytest.raises(
        SnapshotConflictError,
        match=r"fixture-001.*abc123.*different",
    ):
        ingest_snapshot(connection, snapshot, "different")

    counts_after = tuple(
        connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("snapshot", "person", "assertion", "relationship_assertion")
    )
    assert counts_after == counts_before


def test_snapshot_identity_is_immutable_at_the_database_boundary(
    tmp_path: Path,
) -> None:
    """A direct SQL update must not bypass snapshot ID and hash immutability."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
        connection.execute(
            """
            UPDATE snapshot
            SET manifest_sha256 = 'different'
            WHERE snapshot_id = 'fixture-001'
            """
        )

    assert connection.execute(
        """
        SELECT snapshot_id, manifest_sha256
        FROM snapshot
        """
    ).fetchone() == ("fixture-001", "abc123")


def test_insert_or_replace_cannot_change_snapshot_manifest(tmp_path: Path) -> None:
    """SQLite conflict replacement must not bypass immutable snapshot identity."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    with pytest.raises(sqlite3.IntegrityError, match="append-only|conflict"):
        connection.execute(
            """
            INSERT OR REPLACE INTO snapshot(
                snapshot_id, manifest_sha256, source_system,
                source_person_count, source_family_count,
                source_child_link_count, source_event_count, source_place_count
            ) VALUES ('fixture-001', 'different', 'rootsmagic', 0, 0, 0, 0, 0)
            """
        )

    assert connection.execute(
        "SELECT manifest_sha256 FROM snapshot WHERE snapshot_id = 'fixture-001'"
    ).fetchone()[0] == "abc123"


def test_snapshot_rows_cannot_be_deleted(tmp_path: Path) -> None:
    """Deleting an acquisition record would violate append-only provenance."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(
            "DELETE FROM snapshot WHERE snapshot_id = 'fixture-001'"
        )

    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 1


def test_failed_ingestion_rolls_back_the_entire_snapshot(tmp_path: Path) -> None:
    """A bad relationship endpoint must not leave a partially imported snapshot."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    invalid_relationship = replace(
        snapshot.relationships[0],
        object_person_id="missing",
    )
    invalid_snapshot = replace(
        snapshot,
        relationships=(invalid_relationship, *snapshot.relationships[1:]),
    )

    with pytest.raises(ValueError, match=r"relationship.*missing"):
        ingest_snapshot(connection, invalid_snapshot, "abc123")

    for table in (
        "snapshot",
        "person",
        "person_identifier",
        "person_identifier_observation",
        "person_observation",
        "event_observation",
        "source",
        "assertion",
        "relationship_assertion",
        "place",
    ):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_snapshot_duplicate_familysearch_id_fails_before_any_write(
    tmp_path: Path,
) -> None:
    """One FSID on two raw people must not collapse their canonical UUIDs."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    conflicting_identifier = RawIdentifier(
        snapshot_id="fixture-001",
        external_person_id="2",
        system="FamilySearch",
        value="AAAA-111",
        source_link_id="duplicate-fsid",
    )
    conflicting_snapshot = replace(
        snapshot,
        identifiers=(*snapshot.identifiers, conflicting_identifier),
    )
    changes_before = connection.total_changes

    with pytest.raises(
        SnapshotIdentityConflictError,
        match=r"AAAA-111.*raw people 1, 2",
    ):
        ingest_snapshot(connection, conflicting_snapshot, "abc123")

    assert connection.total_changes == changes_before
    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM person").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM assertion").fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM person_identifier"
    ).fetchone()[0] == 0


def test_duplicate_familysearch_observations_for_one_person_are_preserved(
    tmp_path: Path,
) -> None:
    """Repeated provenance for one FSID and raw person must remain representable."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    duplicate_observation = RawIdentifier(
        snapshot_id="fixture-001",
        external_person_id="1",
        system="FamilySearch",
        value="AAAA-111",
        source_link_id="duplicate-observation",
    )
    snapshot = replace(
        snapshot,
        identifiers=(*snapshot.identifiers, duplicate_observation),
    )

    ingest_snapshot(connection, snapshot, "abc123")

    assert connection.execute(
        """
        SELECT observation_ordinal, external_person_id, system, value,
               source_link_id
        FROM person_identifier_observation
        WHERE lower(system) = 'familysearch' AND value = 'AAAA-111'
        ORDER BY observation_ordinal
        """
    ).fetchall() == [
        (0, "1", "familysearch", "AAAA-111", "1"),
        (3, "1", "FamilySearch", "AAAA-111", "duplicate-observation"),
    ]
    assert connection.execute(
        """
        SELECT count(*)
        FROM person_identifier
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        """
    ).fetchone()[0] == 1


def test_familysearch_identifier_reuses_person_across_snapshots(
    tmp_path: Path,
) -> None:
    """Ignoring FSID precedence would mint duplicate people for refreshed imports."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    first_snapshot = _fixture_snapshot(tmp_path, "fixture-001")
    second_snapshot = replace(
        first_snapshot,
        snapshot_id="fixture-002",
        people=tuple(
            replace(person, snapshot_id="fixture-002")
            for person in first_snapshot.people
        ),
        identifiers=tuple(
            replace(
                identifier,
                snapshot_id="fixture-002",
                source_link_id=f"second-{identifier.source_link_id}",
            )
            for identifier in first_snapshot.identifiers
        ),
        relationships=tuple(
            replace(relationship, snapshot_id="fixture-002")
            for relationship in first_snapshot.relationships
        ),
        events=tuple(
            replace(event, snapshot_id="fixture-002")
            for event in first_snapshot.events
        ),
        places=tuple(
            replace(place, snapshot_id="fixture-002")
            for place in first_snapshot.places
        ),
    )

    ingest_snapshot(connection, first_snapshot, "first-hash")
    second = ingest_snapshot(connection, second_snapshot, "second-hash")

    assert second.people_added == 0
    assert connection.execute("SELECT count(*) FROM person").fetchone()[0] == 3
    assert connection.execute(
        """
        SELECT first_seen_snapshot_id, last_seen_snapshot_id
        FROM person_identifier
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        """
    ).fetchone() == ("fixture-001", "fixture-002")
    assert connection.execute(
        """
        SELECT snapshot_id, external_person_id, system, value, source_link_id
        FROM person_identifier_observation
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        ORDER BY snapshot_id
        """
    ).fetchall() == [
        ("fixture-001", "1", "familysearch", "AAAA-111", "1"),
        ("fixture-002", "1", "familysearch", "AAAA-111", "second-1"),
    ]


def test_cross_snapshot_raw_person_and_event_observations_remain_independent(
    tmp_path: Path,
) -> None:
    """Canonical reuse must not collapse sex, name, flags, or event history."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    first_snapshot = _fixture_snapshot(tmp_path, "fixture-001")
    second_person = replace(
        first_snapshot.people[0],
        snapshot_id="fixture-002",
        primary_name_id="101",
        primary_name="Changed Given ChangedSurname Sr.",
        surname="ChangedSurname",
        given="Changed Given",
        suffix="Sr.",
        sex=1,
        living=True,
        private=True,
        source_parent_family_id="77",
    )
    second_identifier = replace(
        first_snapshot.identifiers[0],
        snapshot_id="fixture-002",
        external_person_id=second_person.external_person_id,
        source_link_id="901",
    )
    second_event = replace(
        first_snapshot.events[0],
        snapshot_id="fixture-002",
        fact_type_id="91",
        fact_type_name="Alternate Birth",
        raw_date="DB+19010101..+00000000..",
        date=parse_rm_date("DB+19010101..+00000000.."),
        external_place_id=None,
        raw_place_name=None,
        details="Second details",
        note="Second note",
        private=True,
    )
    second_snapshot = replace(
        first_snapshot,
        snapshot_id="fixture-002",
        people=(second_person,),
        identifiers=(second_identifier,),
        relationships=(),
        events=(second_event,),
        places=(),
        source_family_count=0,
        source_child_link_count=0,
    )

    ingest_snapshot(connection, first_snapshot, "first-hash")
    ingest_snapshot(connection, second_snapshot, "second-hash")
    canonical_person_id = connection.execute(
        """
        SELECT person_id FROM person_identifier
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        """
    ).fetchone()[0]

    assert connection.execute(
        """
        SELECT snapshot_id, external_person_id, primary_name_id, primary_name,
               surname, given_name, suffix, sex, living, private,
               source_parent_family_id
        FROM person_observation
        WHERE person_id = ?
        ORDER BY snapshot_id
        """,
        (canonical_person_id,),
    ).fetchall() == [
        (
            "fixture-001",
            "1",
            "1",
            "Parent One Example",
            "Example",
            "Parent One",
            "",
            0,
            0,
            0,
            None,
        ),
        (
            "fixture-002",
            "1",
            "101",
            "Changed Given ChangedSurname Sr.",
            "ChangedSurname",
            "Changed Given",
            "Sr.",
            1,
            1,
            1,
            "77",
        ),
    ]
    assert connection.execute(
        """
        SELECT sex, count(*)
        FROM person_observation
        WHERE person_id = ?
        GROUP BY sex
        ORDER BY sex
        """,
        (canonical_person_id,),
    ).fetchall() == [(0, 1), (1, 1)]
    assert connection.execute(
        """
        SELECT snapshot_id, fact_type_id, fact_type_name, raw_date,
               date_modifier, date_start_year, date_start_month, date_start_day,
               date_parse_status, details, note, private
        FROM event_observation
        WHERE person_id = ?
        ORDER BY snapshot_id
        """,
        (canonical_person_id,),
    ).fetchall() == [
        (
            "fixture-001",
            "1",
            "Birth",
            "D.+19000102..+00000000..",
            "exact",
            1900,
            1,
            2,
            "parsed",
            "Imported detail",
            "Imported note",
            0,
        ),
        (
            "fixture-002",
            "91",
            "Alternate Birth",
            "DB+19010101..+00000000..",
            "before",
            1901,
            1,
            1,
            "parsed",
            "Second details",
            "Second note",
            1,
        ),
    ]


def test_rootsmagic_rin_is_scoped_and_names_never_trigger_a_merge(
    tmp_path: Path,
) -> None:
    """Same RINs and names in another snapshot must not imply identity without FSIDs."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    first_snapshot = _fixture_snapshot(tmp_path, "fixture-001")
    first_without_fsids = replace(first_snapshot, identifiers=())
    second_snapshot = replace(
        first_without_fsids,
        snapshot_id="fixture-002",
        people=tuple(
            replace(person, snapshot_id="fixture-002")
            for person in first_without_fsids.people
        ),
        relationships=tuple(
            replace(relationship, snapshot_id="fixture-002")
            for relationship in first_without_fsids.relationships
        ),
        events=tuple(
            replace(event, snapshot_id="fixture-002")
            for event in first_without_fsids.events
        ),
        places=tuple(
            replace(place, snapshot_id="fixture-002")
            for place in first_without_fsids.places
        ),
    )

    ingest_snapshot(connection, first_without_fsids, "first-hash")
    second = ingest_snapshot(connection, second_snapshot, "second-hash")

    assert second.people_added == 3
    assert connection.execute("SELECT count(*) FROM person").fetchone()[0] == 6
    assert connection.execute(
        """
        SELECT count(*)
        FROM person_identifier
        WHERE system = 'rootsmagic_rin' AND value = '1'
        """
    ).fetchone()[0] == 2


def test_familysearch_precedence_does_not_depend_on_identifier_order(
    tmp_path: Path,
) -> None:
    """Looking at RIN before FSID would make identity depend on raw record ordering."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    first_snapshot = _fixture_snapshot(tmp_path, "fixture-001")
    ingest_snapshot(connection, first_snapshot, "first-hash")
    raw_person = replace(
        first_snapshot.people[0],
        snapshot_id="fixture-002",
        external_person_id="999",
    )
    raw_identifier = RawIdentifier(
        "fixture-002",
        "999",
        "familysearch",
        "AAAA-111",
        "900",
    )
    second_snapshot = replace(
        first_snapshot,
        snapshot_id="fixture-002",
        people=(raw_person,),
        identifiers=(raw_identifier,),
        relationships=(),
        events=(),
        places=(),
        source_family_count=0,
        source_child_link_count=0,
    )
    original_person_id = connection.execute(
        """
        SELECT person_id FROM person_identifier
        WHERE system = 'familysearch' AND value = 'AAAA-111'
        """
    ).fetchone()[0]

    result = ingest_snapshot(connection, second_snapshot, "second-hash")

    assert result.people_added == 0
    assert connection.execute(
        """
        SELECT person_id FROM person_identifier
        WHERE system = 'rootsmagic_rin'
          AND scope_snapshot_id = 'fixture-002'
          AND value = '999'
        """
    ).fetchone()[0] == original_person_id


def test_non_familysearch_identifiers_are_preserved_without_driving_identity(
    tmp_path: Path,
) -> None:
    """Discarding a generic RawIdentifier would break raw provenance preservation."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    ancestry_identifier = RawIdentifier(
        "fixture-001",
        "1",
        "ancestry",
        "profile-123",
        "44",
    )
    snapshot = replace(
        snapshot,
        identifiers=(*snapshot.identifiers, ancestry_identifier),
    )

    ingest_snapshot(connection, snapshot, "abc123")

    assert connection.execute(
        """
        SELECT system, value, scope_snapshot_id
        FROM person_identifier
        WHERE system = 'ancestry'
        """
    ).fetchone() == ("ancestry", "profile-123", "fixture-001")
    assert connection.execute(
        """
        SELECT snapshot_id, external_person_id, system, value, source_link_id
        FROM person_identifier_observation
        WHERE system = 'ancestry'
        """
    ).fetchone() == (
        "fixture-001",
        "1",
        "ancestry",
        "profile-123",
        "44",
    )


def test_duplicate_raw_identifier_link_ids_are_preserved_by_ordinal(
    tmp_path: Path,
) -> None:
    """A source link ID collision must not collapse representable raw observations."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    snapshot = _fixture_snapshot(tmp_path)
    duplicate_link_observations = (
        RawIdentifier("fixture-001", "1", "ancestry", "profile-123", "44"),
        RawIdentifier("fixture-001", "1", "ancestry", "profile-456", "44"),
    )
    snapshot = replace(
        snapshot,
        identifiers=(*snapshot.identifiers, *duplicate_link_observations),
    )

    ingest_snapshot(connection, snapshot, "abc123")

    assert connection.execute(
        """
        SELECT observation_ordinal, external_person_id, system, value,
               source_link_id
        FROM person_identifier_observation
        WHERE system = 'ancestry'
        ORDER BY observation_ordinal
        """
    ).fetchall() == [
        (3, "1", "ancestry", "profile-123", "44"),
        (4, "1", "ancestry", "profile-456", "44"),
    ]


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("person_observation", "primary_name"),
        ("event_observation", "details"),
        ("person_identifier_observation", "source_link_id"),
    ],
)
def test_raw_observations_are_append_only(
    tmp_path: Path,
    table: str,
    column: str,
) -> None:
    """Raw snapshot evidence must not be updateable or deletable after ingestion."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(f"UPDATE {table} SET {column} = 'changed'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize(
    "replacement_sql",
    [
        """
        INSERT OR REPLACE INTO person_observation(
            person_observation_id, snapshot_id, observation_ordinal, person_id,
            external_person_id, primary_name_id, primary_name, surname,
            given_name, suffix, sex, living, private, source_parent_family_id,
            primary_name_assertion_id, selected_parent_assertion_id
        )
        SELECT person_observation_id, snapshot_id, observation_ordinal, person_id,
               external_person_id, primary_name_id, 'changed', surname,
               given_name, suffix, sex, living, private, source_parent_family_id,
               primary_name_assertion_id, selected_parent_assertion_id
        FROM person_observation
        WHERE observation_ordinal = 0
        """,
        """
        INSERT OR REPLACE INTO event_observation(
            event_observation_id, snapshot_id, observation_ordinal, assertion_id,
            person_id, place_id, external_event_id, owner_type,
            external_owner_id, external_family_id, fact_type_id, fact_type_name,
            raw_date, date_modifier, date_start_year, date_start_month,
            date_start_day, date_end_year, date_end_month, date_end_day,
            date_parse_status, external_place_id, raw_place_name, details,
            note, private
        )
        SELECT event_observation_id, snapshot_id, observation_ordinal, assertion_id,
               person_id, place_id, external_event_id, owner_type,
               external_owner_id, external_family_id, fact_type_id, fact_type_name,
               raw_date, date_modifier, date_start_year, date_start_month,
               date_start_day, date_end_year, date_end_month, date_end_day,
               date_parse_status, external_place_id, raw_place_name, 'changed',
               note, private
        FROM event_observation
        WHERE observation_ordinal = 0
        """,
        """
        INSERT OR REPLACE INTO person_identifier_observation(
            person_identifier_observation_id, snapshot_id, observation_ordinal,
            person_identifier_id, person_id, external_person_id, system, value,
            source_link_id
        )
        SELECT person_identifier_observation_id, snapshot_id, observation_ordinal,
               person_identifier_id, person_id, external_person_id, system, value,
               'changed'
        FROM person_identifier_observation
        WHERE observation_ordinal = 0
        """,
    ],
)
def test_insert_or_replace_cannot_rewrite_raw_observations(
    tmp_path: Path,
    replacement_sql: str,
) -> None:
    """SQLite replacement syntax must not rewrite an existing raw observation."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(replacement_sql)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda snapshot: replace(
                snapshot,
                people=(
                    replace(snapshot.people[0], snapshot_id="wrong"),
                    *snapshot.people[1:],
                ),
            ),
            "RawPerson",
        ),
        (
            lambda snapshot: replace(
                snapshot,
                identifiers=(
                    *snapshot.identifiers,
                    RawIdentifier(
                        "fixture-001",
                        "missing",
                        "ancestry",
                        "orphan",
                        "88",
                    ),
                ),
            ),
            "identifier.*missing",
        ),
    ],
)
def test_invalid_raw_provenance_rolls_back_without_silent_drops(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    """Mismatched or orphaned raw records must not be accepted or skipped."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    invalid_snapshot = mutation(_fixture_snapshot(tmp_path))

    with pytest.raises(ValueError, match=message):
        ingest_snapshot(connection, invalid_snapshot, "abc123")

    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM person").fetchone()[0] == 0


def test_snapshot_relationship_and_assertion_uniqueness_is_enforced(
    tmp_path: Path,
) -> None:
    """Broken uniqueness constraints would permit duplicate provenance claims."""
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_snapshot(connection, _fixture_snapshot(tmp_path), "abc123")

    assertion = connection.execute(
        """
        SELECT subject_type, subject_id, subject_person_id, predicate,
               value_text, raw_value, parsed_value, snapshot_id, source_id,
               place_id, raw_external_assertion_id, raw_external_owner_id,
               raw_external_place_id, is_private
        FROM assertion
        WHERE predicate = 'person.primary_name'
        LIMIT 1
        """
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, subject_person_id, predicate,
                value_text, raw_value, parsed_value, snapshot_id, source_id,
                place_id, raw_external_assertion_id, raw_external_owner_id,
                raw_external_place_id, is_private
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            assertion,
        )

    relationship = connection.execute(
        """
        SELECT subject_person_id, predicate, object_person_id, role,
               snapshot_id, source_id, raw_external_relationship_id,
               raw_external_family_id, raw_external_child_link_id
        FROM relationship_assertion
        WHERE predicate = 'parent_child'
        LIMIT 1
        """
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute(
            """
            INSERT INTO relationship_assertion(
                subject_person_id, predicate, object_person_id, role,
                snapshot_id, source_id, raw_external_relationship_id,
                raw_external_family_id, raw_external_child_link_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            relationship,
        )
