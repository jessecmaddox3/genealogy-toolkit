from dataclasses import FrozenInstanceError
from pathlib import Path
import sqlite3

import pytest

from genealogy.records import (
    RawIdentifier,
    RawRelationship,
)
from genealogy.rm_dates import PartialDate
from genealogy.rm_reader import RootsMagicExtractionError, extract_snapshot
from tests.fixtures.rm_fixture import build_rm_fixture


def test_extract_snapshot_preserves_relationships_and_raw_values(
    tmp_path: Path,
) -> None:
    """Changing source ordering, joins, or raw fields must change this result."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")

    snapshot = extract_snapshot(path, "fixture-001")

    assert snapshot.snapshot_id == "fixture-001"
    assert snapshot.source_family_count == 1
    assert snapshot.source_child_link_count == 1
    assert len(snapshot.people) == 3
    assert snapshot.people[2].external_person_id == "3"
    assert snapshot.people[2].primary_name == "Child Example"
    assert snapshot.people[2].primary_name_id == "3"
    assert snapshot.people[2].living is True
    assert snapshot.people[2].private is True
    assert snapshot.identifiers == (
        RawIdentifier("fixture-001", "1", "familysearch", "AAAA-111", "1"),
        RawIdentifier("fixture-001", "2", "familysearch", "BBBB-222", "2"),
        RawIdentifier("fixture-001", "3", "familysearch", "CCCC-333", "3"),
    )
    assert snapshot.relationships == (
        RawRelationship(
            "fixture-001", "parent_child", "1", "3", "father", "1", "1"
        ),
        RawRelationship(
            "fixture-001", "parent_child", "2", "3", "mother", "1", "1"
        ),
        RawRelationship(
            "fixture-001", "spouse", "1", "2", None, "1", None
        ),
    )
    assert snapshot.events[0].external_event_id == "1"
    assert snapshot.events[0].external_owner_id == "1"
    assert snapshot.events[0].fact_type_id == "1"
    assert snapshot.events[0].fact_type_name == "Birth"
    assert snapshot.events[0].raw_date == "D.+19000102..+00000000.."
    assert snapshot.events[0].date.start == PartialDate(1900, 1, 2)
    assert snapshot.events[0].external_place_id == "1"
    assert snapshot.events[0].raw_place_name == (
        "Larkhaven, Mistvale, Fictional Republic"
    )
    assert snapshot.events[0].details == "Imported detail"
    assert snapshot.events[0].note == "Imported note"
    assert snapshot.events[2].external_place_id is None
    assert snapshot.events[2].raw_place_name is None
    assert snapshot.places[0].external_place_id == "1"
    assert snapshot.places[0].raw_name == (
        "Larkhaven, Mistvale, Fictional Republic"
    )
    assert all(
        record.snapshot_id == "fixture-001"
        for records in (
            snapshot.people,
            snapshot.identifiers,
            snapshot.relationships,
            snapshot.events,
            snapshot.places,
        )
        for record in records
    )


def test_extracted_records_are_immutable_and_slotted(tmp_path: Path) -> None:
    """Removing frozen or slots from a raw record must violate the contract."""
    snapshot = extract_snapshot(
        build_rm_fixture(tmp_path / "fixture.rmtree"), "fixture-001"
    )

    records = (
        snapshot,
        snapshot.people[0],
        snapshot.identifiers[0],
        snapshot.relationships[0],
        snapshot.events[0],
        snapshot.places[0],
    )
    for record in records:
        assert not hasattr(record, "__dict__")
        with pytest.raises(FrozenInstanceError):
            record.snapshot_id = "changed"


def test_extract_snapshot_preserves_selected_parent_family(
    tmp_path: Path,
) -> None:
    """Dropping PersonTable.ParentID would hide RootsMagic's selected family."""
    path = build_rm_fixture(
        tmp_path / "fixture.rmtree",
        include_alternate_parent_family=True,
    )

    snapshot = extract_snapshot(path, "fixture-001")

    assert snapshot.people[2].source_parent_family_id == "2"
    assert [
        relationship.source_family_id
        for relationship in snapshot.relationships
        if relationship.kind == "parent_child"
    ] == ["1", "1", "2"]


def test_extract_snapshot_rejects_missing_child_target(tmp_path: Path) -> None:
    """An inner join must not silently discard a dangling ChildTable child."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")
    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM PersonTable WHERE PersonID = 3")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        RootsMagicExtractionError,
        match=r"ChildTable\.RecID=1.*PersonTable\.PersonID=3",
    ):
        extract_snapshot(path, "fixture-001")


def test_extract_snapshot_rejects_missing_family_target(tmp_path: Path) -> None:
    """An inner join must not silently discard a dangling ChildTable family."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")
    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM FamilyTable WHERE FamilyID = 1")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        RootsMagicExtractionError,
        match=r"ChildTable\.RecID=1.*FamilyTable\.FamilyID=1",
    ):
        extract_snapshot(path, "fixture-001")
