"""Validated ingestion of private family bridge records."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from genealogy.integrity import require_consistent_working_graph
from genealogy.identity import add_global_identifier, resolve_exact_person


class SeedValidationError(ValueError):
    """Raised when a private seed does not meet its strict input contract."""


@dataclass(frozen=True, slots=True)
class SeedPerson:
    """One private person, optionally anchored by an exact FamilySearch ID."""

    seed_id: str
    display_name: str
    living: bool
    familysearch_id: str | None = None


@dataclass(frozen=True, slots=True)
class SeedRelationship:
    """One asserted parent-child bridge between seed people."""

    parent: str
    child: str


@dataclass(frozen=True, slots=True)
class PrivateSeed:
    """A validated collection of private people and parent relationships."""

    people: tuple[SeedPerson, ...]
    relationships: tuple[SeedRelationship, ...]


def _require_object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SeedValidationError(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise SeedValidationError(f"{context} keys must be strings")
    return value


def _require_nonempty_string(
    record: dict[str, object], field: str, context: str
) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SeedValidationError(f"{context} {field} must be a non-empty string")
    return value.strip()


def _reject_unknown_fields(
    record: dict[str, object], allowed: set[str], context: str
) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise SeedValidationError(
            f"{context} has unknown field{'s' if len(unknown) != 1 else ''} "
            f"{', '.join(unknown)}"
        )


def load_private_seed(path: Path) -> PrivateSeed:
    """Load and strictly validate a private JSON family bridge."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SeedValidationError(f"cannot load private seed: {error}") from error

    root = _require_object(payload, "seed")
    _reject_unknown_fields(root, {"people", "relationships"}, "seed")
    raw_people = root.get("people")
    raw_relationships = root.get("relationships")
    if not isinstance(raw_people, list) or not raw_people:
        raise SeedValidationError("seed people must be a non-empty list")
    if not isinstance(raw_relationships, list):
        raise SeedValidationError("seed relationships must be a list")

    people: list[SeedPerson] = []
    seed_ids: set[str] = set()
    familysearch_ids: set[str] = set()
    for index, raw_person in enumerate(raw_people):
        context = f"person {index}"
        person = _require_object(raw_person, context)
        _reject_unknown_fields(
            person,
            {"seed_id", "display_name", "living", "familysearch_id"},
            context,
        )
        seed_id = _require_nonempty_string(person, "seed_id", context)
        if seed_id in seed_ids:
            raise SeedValidationError(f"duplicate seed_id {seed_id}")
        seed_ids.add(seed_id)
        display_name = _require_nonempty_string(person, "display_name", context)
        living = person.get("living")
        if not isinstance(living, bool):
            raise SeedValidationError(f"{context} living must be a boolean")
        familysearch_id = person.get("familysearch_id")
        if familysearch_id is not None:
            if not isinstance(familysearch_id, str) or not familysearch_id.strip():
                raise SeedValidationError(
                    f"{context} familysearch_id must be null or a non-empty string"
                )
            familysearch_id = familysearch_id.strip()
            if living:
                raise SeedValidationError(
                    f"living person {seed_id} cannot include a FamilySearch ID"
                )
            if familysearch_id in familysearch_ids:
                raise SeedValidationError(
                    f"duplicate FamilySearch ID {familysearch_id}"
                )
            familysearch_ids.add(familysearch_id)
        people.append(
            SeedPerson(
                seed_id=seed_id,
                display_name=display_name,
                living=living,
                familysearch_id=familysearch_id,
            )
        )

    relationships: list[SeedRelationship] = []
    seen_relationships: set[tuple[str, str]] = set()
    for index, raw_relationship in enumerate(raw_relationships):
        context = f"relationship {index}"
        relationship = _require_object(raw_relationship, context)
        _reject_unknown_fields(relationship, {"parent", "child"}, context)
        parent = _require_nonempty_string(relationship, "parent", context)
        child = _require_nonempty_string(relationship, "child", context)
        for endpoint in (parent, child):
            if endpoint not in seed_ids:
                raise SeedValidationError(
                    f"{context} references unknown person {endpoint}"
                )
        if parent == child:
            raise SeedValidationError(
                f"{context} cannot make {parent} their own parent"
            )
        edge = (parent, child)
        if edge in seen_relationships:
            raise SeedValidationError(
                f"duplicate parent relationship {parent} -> {child}"
            )
        seen_relationships.add(edge)
        relationships.append(SeedRelationship(parent=parent, child=child))

    return PrivateSeed(tuple(people), tuple(relationships))


def _seed_digest(seed: PrivateSeed) -> str:
    payload = {
        "format_version": 2,
        "people": [asdict(person) for person in seed.people],
        "relationships": [
            asdict(relationship) for relationship in seed.relationships
        ],
    }
    canonical_json = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _family_ids_by_child(seed: PrivateSeed) -> dict[str, str]:
    parents_by_child: dict[str, list[str]] = {}
    for relationship in seed.relationships:
        parents_by_child.setdefault(relationship.child, []).append(
            relationship.parent
        )
    family_ids: dict[str, str] = {}
    for child, parents in parents_by_child.items():
        parent_key = json.dumps(sorted(parents), separators=(",", ":"))
        digest = hashlib.sha256(parent_key.encode("utf-8")).hexdigest()
        family_ids[child] = f"private-seed-family-{digest[:24]}"
    return family_ids


def _resolve_person_id(
    connection: sqlite3.Connection, person: SeedPerson
) -> str:
    identifiers = {"private_seed": person.seed_id}
    if person.familysearch_id is not None:
        identifiers["familysearch"] = person.familysearch_id
    try:
        return resolve_exact_person(connection, identifiers)
    except ValueError as error:
        if person.familysearch_id is None:
            raise
        raise ValueError(
            f"seed_id {person.seed_id} and FamilySearch ID "
            f"{person.familysearch_id} resolve to different canonical people"
        ) from error


def _store_name_conclusion(
    connection: sqlite3.Connection,
    person_id: str,
    assertion_id: int,
) -> None:
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            confidence, rationale
        ) VALUES (
            'person', ?, 'person.primary_name', ?,
            'accepted_working', 'Private family seed'
        )
        ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
            chosen_assertion_id = excluded.chosen_assertion_id,
            chosen_relationship_assertion_id = NULL,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (person_id, assertion_id),
    )


def _store_relationship_conclusion(
    connection: sqlite3.Connection, relationship_assertion_id: int
) -> None:
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES (
            'relationship', ?, 'parent_child', ?,
            'accepted_working', 'Private family seed'
        )
        ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
            chosen_assertion_id = NULL,
            chosen_relationship_assertion_id =
                excluded.chosen_relationship_assertion_id,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            str(relationship_assertion_id),
            relationship_assertion_id,
        ),
    )


def ingest_private_seed(
    connection: sqlite3.Connection, seed: PrivateSeed
) -> None:
    """Atomically ingest a validated seed without fuzzy identity matching."""
    if connection.in_transaction:
        raise sqlite3.ProgrammingError(
            "ingest_private_seed requires a connection without an active transaction"
        )

    digest = _seed_digest(seed)
    snapshot_id = f"private-seed-{digest[:24]}"
    family_ids_by_child = _family_ids_by_child(seed)
    connection.execute("BEGIN IMMEDIATE")
    try:
        if connection.execute(
            "SELECT 1 FROM snapshot WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone():
            connection.execute("COMMIT")
            return

        connection.execute(
            """
            INSERT INTO snapshot(
                snapshot_id, manifest_sha256, source_system, import_scope,
                source_person_count, source_family_count,
                source_child_link_count, source_event_count, source_place_count
            ) VALUES (?, ?, 'private_seed', 'private family bridge', ?, ?, ?, 0, 0)
            """,
            (
                snapshot_id,
                digest,
                len(seed.people),
                len(set(family_ids_by_child.values())),
                len(seed.relationships),
            ),
        )
        source_id = connection.execute(
            """
            INSERT INTO source(
                snapshot_id, source_type, record_title, evidence_tier
            ) VALUES (?, 'private_seed', ?, 'family_knowledge')
            """,
            (snapshot_id, f"Private family seed {digest[:12]}"),
        ).lastrowid

        canonical_ids: dict[str, str] = {}
        for person in seed.people:
            person_id = _resolve_person_id(connection, person)
            canonical_ids[person.seed_id] = person_id
            exists = connection.execute(
                "SELECT 1 FROM person WHERE person_id = ?", (person_id,)
            ).fetchone()
            if exists is None:
                connection.execute(
                    """
                    INSERT INTO person(person_id, living, private)
                    VALUES (?, ?, ?)
                    """,
                    (person_id, int(person.living), int(person.living)),
                )
            elif person.living:
                connection.execute(
                    """
                    UPDATE person
                    SET living = 1, private = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE person_id = ? AND (living = 0 OR private = 0)
                    """,
                    (person_id,),
                )

            add_global_identifier(
                connection,
                person_id=person_id,
                system="private_seed",
                value=person.seed_id,
                snapshot_id=snapshot_id,
            )
            if person.familysearch_id is not None:
                add_global_identifier(
                    connection,
                    person_id=person_id,
                    system="familysearch",
                    value=person.familysearch_id,
                    snapshot_id=snapshot_id,
                )

            assertion_id = connection.execute(
                """
                INSERT INTO assertion(
                    subject_type, subject_id, subject_person_id, predicate,
                    value_text, raw_value, snapshot_id, source_id,
                    raw_external_assertion_id, raw_external_owner_id,
                    is_private
                ) VALUES (
                    'person', ?, ?, 'person.primary_name', ?, ?, ?, ?, ?, ?, 1
                )
                """,
                (
                    person_id,
                    person_id,
                    person.display_name,
                    person.display_name,
                    snapshot_id,
                    source_id,
                    f"name:{person.seed_id}",
                    person.seed_id,
                ),
            ).lastrowid
            _store_name_conclusion(connection, person_id, assertion_id)

        for relationship in seed.relationships:
            if canonical_ids[relationship.parent] == canonical_ids[relationship.child]:
                raise SeedValidationError("Exact identity matching would make a person their own parent; the seed was not imported")
            relationship_assertion_id = connection.execute(
                """
                INSERT INTO relationship_assertion(
                    subject_person_id, predicate, object_person_id, role,
                    snapshot_id, source_id, raw_external_relationship_id,
                    raw_external_family_id, raw_external_child_link_id
                ) VALUES (?, 'parent_child', ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_ids[relationship.parent],
                    canonical_ids[relationship.child],
                    snapshot_id,
                    source_id,
                    (
                        f"parent:{relationship.parent}:"
                        f"child:{relationship.child}"
                    ),
                    family_ids_by_child[relationship.child],
                    f"{relationship.parent}:{relationship.child}",
                ),
            ).lastrowid
            _store_relationship_conclusion(
                connection, relationship_assertion_id
            )

        require_consistent_working_graph(connection)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
