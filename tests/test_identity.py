"""Tests for resolving people from exact global identifiers."""

from pathlib import Path
import sqlite3
import uuid

import pytest

from genealogy.identity import add_global_identifier, resolve_exact_person
from genealogy.store import create_store


def _add_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES (?, ?, 'test', 0, 0, 0, 0, 0)
        """,
        (snapshot_id, snapshot_id),
    )


def test_resolve_exact_person_uses_matching_identifiers_or_mints_uuid(
    tmp_path: Path,
) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    _add_snapshot(connection, "snapshot-a")
    existing = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO person(person_id, living, private) VALUES (?, 0, 0)",
        (existing,),
    )
    add_global_identifier(
        connection,
        person_id=existing,
        system="familysearch",
        value="AAAA-111",
        snapshot_id="snapshot-a",
    )

    assert resolve_exact_person(
        connection,
        {"familysearch": "AAAA-111", "research_key": "research:case_subject"},
    ) == existing

    minted = resolve_exact_person(
        connection,
        {"research_key": "research:new-person"},
    )
    assert uuid.UUID(minted)
    assert minted != existing


def test_resolve_exact_person_rejects_identifiers_for_different_people(
    tmp_path: Path,
) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    _add_snapshot(connection, "snapshot-a")
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())
    for person_id in (first, second):
        connection.execute(
            "INSERT INTO person(person_id, living, private) VALUES (?, 0, 0)",
            (person_id,),
        )
    add_global_identifier(
        connection,
        person_id=first,
        system="familysearch",
        value="AAAA-111",
        snapshot_id="snapshot-a",
    )
    add_global_identifier(
        connection,
        person_id=second,
        system="research_key",
        value="research:case_subject",
        snapshot_id="snapshot-a",
    )

    with pytest.raises(
        ValueError,
        match="Identifiers resolve to different canonical people",
    ):
        resolve_exact_person(
            connection,
            {"familysearch": "AAAA-111", "research_key": "research:case_subject"},
        )
