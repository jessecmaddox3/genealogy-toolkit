"""Resolution and storage of exact global person identifiers."""

import sqlite3
import uuid
from collections.abc import Mapping


def find_global_identifier_person(
    connection: sqlite3.Connection,
    system: str,
    value: str,
) -> str | None:
    """Return the canonical person for an exact global identifier, if present."""
    row = connection.execute(
        """
        SELECT person_id
        FROM person_identifier
        WHERE system = ? AND value = ? AND scope_snapshot_id IS NULL
        """,
        (system, value),
    ).fetchone()
    return None if row is None else row[0]


def add_global_identifier(
    connection: sqlite3.Connection,
    *,
    person_id: str,
    system: str,
    value: str,
    snapshot_id: str,
) -> None:
    """Store an exact global identifier, or update its last-seen snapshot."""
    row = connection.execute(
        """
        SELECT person_identifier_id, person_id
        FROM person_identifier
        WHERE system = ? AND value = ? AND scope_snapshot_id IS NULL
        """,
        (system, value),
    ).fetchone()
    if row is None:
        connection.execute(
            """
            INSERT INTO person_identifier(
                person_id, system, value, scope_snapshot_id,
                first_seen_snapshot_id, last_seen_snapshot_id
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (person_id, system, value, snapshot_id, snapshot_id),
        )
        return
    if row[1] != person_id:
        raise ValueError(
            f"Identifier {system}:{value} is already assigned to another person"
        )
    connection.execute(
        """
        UPDATE person_identifier
        SET last_seen_snapshot_id = ?
        WHERE person_identifier_id = ?
          AND last_seen_snapshot_id != ?
        """,
        (snapshot_id, row[0], snapshot_id),
    )


def resolve_exact_person(
    connection: sqlite3.Connection,
    identifiers: Mapping[str, str],
) -> str:
    """Resolve exact global identifiers to one person, or mint a UUID."""
    person_ids = {
        person_id
        for system, value in identifiers.items()
        if (person_id := find_global_identifier_person(connection, system, value))
        is not None
    }
    if len(person_ids) > 1:
        raise ValueError("Identifiers resolve to different canonical people")
    return person_ids.pop() if person_ids else str(uuid.uuid4())
