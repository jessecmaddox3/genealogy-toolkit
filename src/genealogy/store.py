"""Canonical SQLite store creation and atomic snapshot ingestion."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import uuid
from collections.abc import Iterable, Mapping

from genealogy.confidence import ConfidenceDecision, classify_initial_assertion
from genealogy.records import RawSnapshot
from genealogy.integrity import quarantine_working_conflicts


class SnapshotConflictError(RuntimeError):
    """Raised when a snapshot ID is presented with a different manifest hash."""


class SnapshotIdentityConflictError(ValueError):
    """Raised when one raw snapshot assigns an identity to multiple people."""


ConfidenceAnnotations = Mapping[tuple[str, ...], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Counts added by one atomic snapshot ingestion."""

    snapshot_id: str
    people_added: int
    assertions_added: int
    relationships_added: int


def create_store(path: Path) -> sqlite3.Connection:
    """Create or open a canonical store with referential integrity enabled."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        core = {'person', 'snapshot', 'source', 'assertion', 'relationship_assertion', 'conclusion'}
        if tables and not core.issubset(tables):
            raise ValueError("Refusing to change an existing database that is not a genealogy canonical store. Choose a new output database.")
    except BaseException:
        connection.close()
        raise
    schema_path = Path(__file__).with_name("schema.sql")
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
    except Exception:
        connection.close()
        raise
    return connection


def _event_predicate(fact_type_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", fact_type_name.casefold()).strip("_")
    return f"event.{normalized or 'unknown'}"


def _parsed_date_json(parsed_date: object) -> str:
    value = asdict(parsed_date)
    value.pop("original")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _familysearch_identifiers(snapshot: RawSnapshot) -> dict[str, tuple[object, ...]]:
    by_person: dict[str, list[object]] = {}
    for identifier in snapshot.identifiers:
        if identifier.system.casefold() == "familysearch" and identifier.value:
            by_person.setdefault(identifier.external_person_id, []).append(identifier)
    return {
        external_person_id: tuple(identifiers)
        for external_person_id, identifiers in by_person.items()
    }


def _validate_snapshot_provenance(snapshot: RawSnapshot) -> None:
    external_person_ids = {
        person.external_person_id for person in snapshot.people
    }
    for records in (
        snapshot.people,
        snapshot.identifiers,
        snapshot.relationships,
        snapshot.events,
        snapshot.places,
    ):
        for record in records:
            if record.snapshot_id != snapshot.snapshot_id:
                raise ValueError(
                    f"{type(record).__name__} has snapshot_id "
                    f"{record.snapshot_id!r}, expected {snapshot.snapshot_id!r}"
                )
    for identifier in snapshot.identifiers:
        if identifier.external_person_id not in external_person_ids:
            raise ValueError(
                f"identifier {identifier.system}:{identifier.value} references "
                f"missing person {identifier.external_person_id}"
            )

    familysearch_people: dict[str, set[str]] = {}
    for identifier in snapshot.identifiers:
        if (
            identifier.system.casefold() == "familysearch"
            and identifier.value
        ):
            familysearch_people.setdefault(identifier.value, set()).add(
                identifier.external_person_id
            )
    for familysearch_id in sorted(familysearch_people):
        raw_person_ids = familysearch_people[familysearch_id]
        if len(raw_person_ids) > 1:
            people = ", ".join(sorted(raw_person_ids))
            raise SnapshotIdentityConflictError(
                f"FamilySearch ID {familysearch_id} in snapshot "
                f"{snapshot.snapshot_id} maps to raw people {people}"
            )


def _global_identifier_person(
    connection: sqlite3.Connection, system: str, value: str
) -> str | None:
    row = connection.execute(
        """
        SELECT person_id
        FROM person_identifier
        WHERE system = ? AND value = ? AND scope_snapshot_id IS NULL
        """,
        (system, value),
    ).fetchone()
    return None if row is None else row[0]


def _scoped_rin_person(
    connection: sqlite3.Connection, snapshot_id: str, rin: str
) -> str | None:
    row = connection.execute(
        """
        SELECT person_id
        FROM person_identifier
        WHERE system = 'rootsmagic_rin'
          AND scope_snapshot_id = ?
          AND value = ?
        """,
        (snapshot_id, rin),
    ).fetchone()
    return None if row is None else row[0]


def _assign_person_id(
    connection: sqlite3.Connection,
    snapshot_id: str,
    external_person_id: str,
    familysearch_ids: tuple[object, ...],
) -> str:
    familysearch_people = {
        person_id
        for identifier in familysearch_ids
        if (
            person_id := _global_identifier_person(
                connection, "familysearch", identifier.value
            )
        )
        is not None
    }
    if len(familysearch_people) > 1:
        raise ValueError(
            f"FamilySearch identifiers for RootsMagic person "
            f"{external_person_id} resolve to multiple canonical people"
        )
    if familysearch_people:
        return familysearch_people.pop()

    rin_person = _scoped_rin_person(
        connection, snapshot_id, external_person_id
    )
    if rin_person is not None:
        return rin_person
    return str(uuid.uuid4())


def _add_or_observe_identifier(
    connection: sqlite3.Connection,
    *,
    person_id: str,
    system: str,
    value: str,
    scope_snapshot_id: str | None,
    snapshot_id: str,
) -> int:
    if scope_snapshot_id is None:
        existing = connection.execute(
            """
            SELECT person_identifier_id, person_id
            FROM person_identifier
            WHERE system = ? AND value = ? AND scope_snapshot_id IS NULL
            """,
            (system, value),
        ).fetchone()
    else:
        existing = connection.execute(
            """
            SELECT person_identifier_id, person_id
            FROM person_identifier
            WHERE system = ? AND value = ? AND scope_snapshot_id = ?
            """,
            (system, value, scope_snapshot_id),
        ).fetchone()

    if existing is None:
        cursor = connection.execute(
            """
            INSERT INTO person_identifier(
                person_id, system, value, scope_snapshot_id,
                first_seen_snapshot_id, last_seen_snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                system,
                value,
                scope_snapshot_id,
                snapshot_id,
                snapshot_id,
            ),
        )
        return cursor.lastrowid

    if existing[1] != person_id:
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
        (snapshot_id, existing[0], snapshot_id),
    )
    return existing[0]


def _insert_snapshot_source(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
    manifest_sha256: str,
) -> int:
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES (?, ?, 'rootsmagic', ?, ?, ?, ?, ?)
        """,
        (
            snapshot.snapshot_id,
            manifest_sha256,
            len(snapshot.people),
            snapshot.source_family_count,
            snapshot.source_child_link_count,
            len(snapshot.events),
            len(snapshot.places),
        ),
    )
    cursor = connection.execute(
        """
        INSERT INTO source(
            snapshot_id, source_type, record_title, evidence_tier
        ) VALUES (?, 'rootsmagic_snapshot', ?, 'tree_aggregate')
        """,
        (snapshot.snapshot_id, f"RootsMagic snapshot {snapshot.snapshot_id}"),
    )
    return cursor.lastrowid


def _insert_people_and_identifiers(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
) -> tuple[dict[str, str], int]:
    identifiers_by_person = _familysearch_identifiers(snapshot)
    canonical_ids: dict[str, str] = {}
    people_added = 0

    for raw_person in snapshot.people:
        familysearch_ids = identifiers_by_person.get(
            raw_person.external_person_id, ()
        )
        person_id = _assign_person_id(
            connection,
            snapshot.snapshot_id,
            raw_person.external_person_id,
            familysearch_ids,
        )
        canonical_ids[raw_person.external_person_id] = person_id
        exists = connection.execute(
            "SELECT 1 FROM person WHERE person_id = ?", (person_id,)
        ).fetchone()
        if exists is None:
            connection.execute(
                """
                INSERT INTO person(person_id, living, private)
                VALUES (?, ?, ?)
                """,
                (person_id, raw_person.living, raw_person.private),
            )
            people_added += 1
        else:
            connection.execute(
                """
                UPDATE person
                SET living = MAX(living, ?),
                    private = MAX(private, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE person_id = ?
                  AND (living < ? OR private < ?)
                """,
                (
                    raw_person.living,
                    raw_person.private,
                    person_id,
                    raw_person.living,
                    raw_person.private,
                ),
            )

        _add_or_observe_identifier(
            connection,
            person_id=person_id,
            system="rootsmagic_rin",
            value=raw_person.external_person_id,
            scope_snapshot_id=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
        )
        for identifier in familysearch_ids:
            _add_or_observe_identifier(
                connection,
                person_id=person_id,
                system="familysearch",
                value=identifier.value,
                scope_snapshot_id=None,
                snapshot_id=snapshot.snapshot_id,
            )

    for observation_ordinal, identifier in enumerate(snapshot.identifiers):
        normalized_system = identifier.system.casefold()
        scope_snapshot_id = (
            None if normalized_system == "familysearch" else snapshot.snapshot_id
        )
        stable_identifier_id = _add_or_observe_identifier(
            connection,
            person_id=canonical_ids[identifier.external_person_id],
            system=normalized_system,
            value=identifier.value,
            scope_snapshot_id=scope_snapshot_id,
            snapshot_id=snapshot.snapshot_id,
        )
        connection.execute(
            """
            INSERT INTO person_identifier_observation(
                snapshot_id, observation_ordinal, person_identifier_id,
                person_id, external_person_id, system, value, source_link_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                observation_ordinal,
                stable_identifier_id,
                canonical_ids[identifier.external_person_id],
                identifier.external_person_id,
                identifier.system,
                identifier.value,
                identifier.source_link_id,
            ),
        )

    return canonical_ids, people_added


def _store_assertion_conclusion(
    connection: sqlite3.Connection,
    *,
    assertion_id: int,
    subject_type: str,
    subject_id: str,
    predicate: str,
    decision: ConfidenceDecision,
) -> None:
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES (?, ?, ?, ?, NULL, ?, ?)
        ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
            chosen_assertion_id = excluded.chosen_assertion_id,
            chosen_relationship_assertion_id = NULL,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            subject_type,
            subject_id,
            predicate,
            assertion_id,
            decision.confidence,
            decision.rationale,
        ),
    )


def _store_relationship_conclusion(
    connection: sqlite3.Connection,
    *,
    relationship_assertion_id: int,
    predicate: str,
    decision: ConfidenceDecision,
) -> None:
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES ('relationship', ?, ?, NULL, ?, ?, ?)
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
            predicate,
            relationship_assertion_id,
            decision.confidence,
            decision.rationale,
        ),
    )


def _initial_decision(
    contradictions: Iterable[str] = (),
    *,
    identity_ambiguity: bool = False,
    annotation: Mapping[str, object] | None = None,
) -> ConfidenceDecision:
    annotation = {} if annotation is None else annotation
    annotated_contradictions = annotation.get("contradictions", ())
    return classify_initial_assertion(
        {
            "source_tier": "tree_aggregate",
            "contradictions": (
                *tuple(contradictions),
                *tuple(annotated_contradictions),
            ),
            "identity_ambiguity": (
                identity_ambiguity
                or bool(annotation.get("identity_ambiguity"))
            ),
        }
    )


def _insert_places(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
    source_id: int,
    confidence_annotations: ConfidenceAnnotations,
) -> tuple[dict[str, int], int]:
    place_ids: dict[str, int] = {}
    assertions_added = 0
    for raw_place in snapshot.places:
        cursor = connection.execute(
            """
            INSERT INTO place(
                snapshot_id, raw_external_place_id, raw_text, place_type
            ) VALUES (?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                raw_place.external_place_id,
                raw_place.raw_name,
                raw_place.place_type,
            ),
        )
        place_id = cursor.lastrowid
        place_ids[raw_place.external_place_id] = place_id
        assertion_cursor = connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, predicate, value_text, raw_value,
                snapshot_id, source_id, place_id, raw_external_assertion_id,
                raw_external_owner_id, raw_external_place_id
            ) VALUES ('place', ?, 'place.raw_text', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(place_id),
                raw_place.raw_name,
                raw_place.raw_name,
                snapshot.snapshot_id,
                source_id,
                place_id,
                raw_place.external_place_id,
                raw_place.external_place_id,
                raw_place.external_place_id,
            ),
        )
        _store_assertion_conclusion(
            connection,
            assertion_id=assertion_cursor.lastrowid,
            subject_type="place",
            subject_id=str(place_id),
            predicate="place.raw_text",
            decision=_initial_decision(
                annotation=confidence_annotations.get(
                    ("place", raw_place.external_place_id)
                )
            ),
        )
        assertions_added += 1
    return place_ids, assertions_added


def _insert_assertions(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
    source_id: int,
    canonical_ids: dict[str, str],
    place_ids: dict[str, int],
    confidence_annotations: ConfidenceAnnotations,
) -> int:
    assertions_added = 0
    for observation_ordinal, raw_person in enumerate(snapshot.people):
        person_id = canonical_ids[raw_person.external_person_id]
        primary_name_cursor = connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, subject_person_id, predicate,
                value_text, raw_value, parsed_value, snapshot_id, source_id,
                raw_external_assertion_id, raw_external_owner_id, is_private
            ) VALUES ('person', ?, ?, 'person.primary_name', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                person_id,
                person_id,
                raw_person.primary_name,
                raw_person.primary_name,
                json.dumps(
                    {
                        "given": raw_person.given,
                        "surname": raw_person.surname,
                        "suffix": raw_person.suffix,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                snapshot.snapshot_id,
                source_id,
                raw_person.primary_name_id,
                raw_person.external_person_id,
                raw_person.private,
            ),
        )
        assertions_added += 1
        _store_assertion_conclusion(
            connection,
            assertion_id=primary_name_cursor.lastrowid,
            subject_type="person",
            subject_id=person_id,
            predicate="person.primary_name",
            decision=_initial_decision(
                annotation=confidence_annotations.get(
                    (
                        "name",
                        raw_person.external_person_id,
                        raw_person.primary_name_id,
                    )
                )
            ),
        )
        selected_parent_assertion_id = None
        if raw_person.source_parent_family_id is not None:
            selected_parent_cursor = connection.execute(
                """
                INSERT INTO assertion(
                    subject_type, subject_id, subject_person_id, predicate,
                    value_text, raw_value, snapshot_id, source_id,
                    raw_external_assertion_id, raw_external_owner_id,
                    is_private
                ) VALUES (
                    'person', ?, ?, 'rootsmagic.selected_parent_family',
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    person_id,
                    person_id,
                    raw_person.source_parent_family_id,
                    raw_person.source_parent_family_id,
                    snapshot.snapshot_id,
                    source_id,
                    raw_person.external_person_id,
                    raw_person.external_person_id,
                    raw_person.private,
                ),
            )
            selected_parent_assertion_id = selected_parent_cursor.lastrowid
            assertions_added += 1
            _store_assertion_conclusion(
                connection,
                assertion_id=selected_parent_assertion_id,
                subject_type="person",
                subject_id=person_id,
                predicate="rootsmagic.selected_parent_family",
                decision=_initial_decision(),
            )

        connection.execute(
            """
            INSERT INTO person_observation(
                snapshot_id, observation_ordinal, person_id,
                external_person_id, primary_name_id, primary_name,
                surname, given_name, suffix, sex, living, private,
                source_parent_family_id, primary_name_assertion_id,
                selected_parent_assertion_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                observation_ordinal,
                person_id,
                raw_person.external_person_id,
                raw_person.primary_name_id,
                raw_person.primary_name,
                raw_person.surname,
                raw_person.given,
                raw_person.suffix,
                raw_person.sex,
                raw_person.living,
                raw_person.private,
                raw_person.source_parent_family_id,
                primary_name_cursor.lastrowid,
                selected_parent_assertion_id,
            ),
        )

    for observation_ordinal, event in enumerate(snapshot.events):
        if event.owner_type == 0:
            person_id = canonical_ids.get(event.external_owner_id)
            if person_id is None:
                raise ValueError(
                    f"event {event.external_event_id} references missing person "
                    f"{event.external_owner_id}"
                )
            subject_type = "person"
            subject_id = person_id
        else:
            person_id = None
            subject_type = "rootsmagic_family"
            subject_id = (
                f"{snapshot.snapshot_id}:{event.external_family_id or event.external_owner_id}"
            )

        place_id = None
        if event.external_place_id is not None:
            place_id = place_ids.get(event.external_place_id)
            if place_id is None:
                raise ValueError(
                    f"event {event.external_event_id} references missing place "
                    f"{event.external_place_id}"
                )
        assertion_cursor = connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, subject_person_id, predicate,
                value_text, raw_value, parsed_value, snapshot_id, source_id,
                place_id, raw_external_assertion_id, raw_external_owner_id,
                raw_external_place_id, is_private
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_type,
                subject_id,
                person_id,
                _event_predicate(event.fact_type_name),
                event.details or None,
                event.raw_date,
                _parsed_date_json(event.date),
                snapshot.snapshot_id,
                source_id,
                place_id,
                event.external_event_id,
                event.external_owner_id,
                event.external_place_id,
                event.private,
            ),
        )
        _store_assertion_conclusion(
            connection,
            assertion_id=assertion_cursor.lastrowid,
            subject_type=subject_type,
            subject_id=subject_id,
            predicate=_event_predicate(event.fact_type_name),
            decision=_initial_decision(
                annotation=confidence_annotations.get(
                    ("event", event.external_event_id)
                )
            ),
        )
        start = event.date.start
        end = event.date.end
        connection.execute(
            """
            INSERT INTO event_observation(
                snapshot_id, observation_ordinal, assertion_id, person_id,
                place_id, external_event_id, owner_type, external_owner_id,
                external_family_id, fact_type_id, fact_type_name, raw_date,
                date_modifier, date_start_year, date_start_month,
                date_start_day, date_end_year, date_end_month, date_end_day,
                date_parse_status, external_place_id, raw_place_name,
                details, note, private
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                snapshot.snapshot_id,
                observation_ordinal,
                assertion_cursor.lastrowid,
                person_id,
                place_id,
                event.external_event_id,
                event.owner_type,
                event.external_owner_id,
                event.external_family_id,
                event.fact_type_id,
                event.fact_type_name,
                event.raw_date,
                event.date.modifier,
                None if start is None else start.year,
                None if start is None else start.month,
                None if start is None else start.day,
                None if end is None else end.year,
                None if end is None else end.month,
                None if end is None else end.day,
                event.date.parse_status,
                event.external_place_id,
                event.raw_place_name,
                event.details,
                event.note,
                event.private,
            ),
        )
        assertions_added += 1
    return assertions_added


def _exact_birth_year(
    connection: sqlite3.Connection,
    snapshot_id: str,
    person_id: str,
) -> int | None:
    rows = connection.execute(
        """
        SELECT parsed_value
        FROM assertion
        WHERE snapshot_id = ?
          AND subject_person_id = ?
          AND predicate = 'event.birth'
        """,
        (snapshot_id, person_id),
    )
    for (parsed_value,) in rows:
        if parsed_value is None:
            continue
        parsed = json.loads(parsed_value)
        if parsed.get("modifier") != "exact":
            continue
        start = parsed.get("start")
        if isinstance(start, dict) and isinstance(start.get("year"), int):
            return start["year"]
    return None


def _relationship_contradictions(
    connection: sqlite3.Connection,
    snapshot_id: str,
    predicate: str,
    subject_person_id: str,
    object_person_id: str,
) -> tuple[str, ...]:
    """Return documented contradiction flags for one relationship edge."""
    if predicate != "parent_child":
        return ()
    if subject_person_id == object_person_id:
        return ("self_parent",)
    parent_birth_year = _exact_birth_year(
        connection, snapshot_id, subject_person_id
    )
    child_birth_year = _exact_birth_year(
        connection, snapshot_id, object_person_id
    )
    if (
        parent_birth_year is not None
        and child_birth_year is not None
        and child_birth_year - parent_birth_year <= 13
    ):
        return ("parent_age_below_13",)
    return ()


def _insert_relationships(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
    source_id: int,
    canonical_ids: dict[str, str],
    confidence_annotations: ConfidenceAnnotations,
) -> int:
    for relationship in snapshot.relationships:
        subject_person_id = canonical_ids.get(relationship.subject_person_id)
        object_person_id = canonical_ids.get(relationship.object_person_id)
        if subject_person_id is None or object_person_id is None:
            missing = (
                relationship.subject_person_id
                if subject_person_id is None
                else relationship.object_person_id
            )
            raise ValueError(
                f"relationship {relationship.kind} references missing person {missing}"
            )
        if relationship.source_child_link_id is None:
            raw_relationship_id = f"family:{relationship.source_family_id}"
        else:
            raw_relationship_id = (
                f"child_link:{relationship.source_child_link_id}"
            )
        cursor = connection.execute(
            """
            INSERT INTO relationship_assertion(
                subject_person_id, predicate, object_person_id, role,
                snapshot_id, source_id, raw_external_relationship_id,
                raw_external_family_id, raw_external_child_link_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_person_id,
                relationship.kind,
                object_person_id,
                relationship.role,
                snapshot.snapshot_id,
                source_id,
                raw_relationship_id,
                relationship.source_family_id,
                relationship.source_child_link_id,
            ),
        )
        prior_review = ()
        if relationship.kind == 'parent_child' and connection.execute("""
            SELECT 1 FROM conclusion c JOIN relationship_assertion r
              ON r.relationship_assertion_id = c.chosen_relationship_assertion_id
            WHERE c.confidence = 'quarantined_contradiction'
              AND r.predicate = 'parent_child' AND r.object_person_id = ?
              AND r.snapshot_id != ?
              AND (r.subject_person_id = ? OR (? IS NOT NULL AND r.role = ?))
            LIMIT 1
        """, (object_person_id, snapshot.snapshot_id, subject_person_id, relationship.role, relationship.role)).fetchone():
            prior_review = ('prior_unresolved_relationship_conflict',)
        _store_relationship_conclusion(
            connection,
            relationship_assertion_id=cursor.lastrowid,
            predicate=relationship.kind,
            decision=_initial_decision(
                (*prior_review, *_relationship_contradictions(
                    connection,
                    snapshot.snapshot_id,
                    relationship.kind,
                    subject_person_id,
                    object_person_id,
                )),
                annotation=confidence_annotations.get(
                    (
                        "relationship",
                        relationship.kind,
                        relationship.subject_person_id,
                        relationship.object_person_id,
                        relationship.role or "",
                        raw_relationship_id,
                    )
                ),
            ),
        )
    return len(snapshot.relationships)


def ingest_snapshot(
    connection: sqlite3.Connection,
    snapshot: RawSnapshot,
    manifest_sha256: str,
    *,
    confidence_annotations: ConfidenceAnnotations | None = None,
) -> IngestResult:
    """Atomically ingest a snapshot with optional per-claim review annotations.

    Annotation keys use raw snapshot identifiers: ``("name", person_id,
    name_id)``, ``("event", event_id)``, ``("place", place_id)``, and
    ``("relationship", kind, subject_id, object_id, role, raw_edge_id)``.
    Values may carry ``identity_ambiguity`` and/or ``contradictions``.
    """
    if not manifest_sha256:
        raise ValueError("manifest_sha256 must not be empty")
    _validate_snapshot_provenance(snapshot)
    if connection.in_transaction:
        raise sqlite3.ProgrammingError(
            "ingest_snapshot requires a connection without an active transaction"
        )
    confidence_annotations = (
        {} if confidence_annotations is None else confidence_annotations
    )

    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT manifest_sha256 FROM snapshot WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if existing is not None:
            if existing[0] != manifest_sha256:
                raise SnapshotConflictError(
                    f"snapshot {snapshot.snapshot_id} already has manifest "
                    f"{existing[0]}; refusing different hash {manifest_sha256}"
                )
            connection.execute("COMMIT")
            return IngestResult(snapshot.snapshot_id, 0, 0, 0)

        source_id = _insert_snapshot_source(
            connection, snapshot, manifest_sha256
        )
        canonical_ids, people_added = _insert_people_and_identifiers(
            connection, snapshot
        )
        place_ids, place_assertions_added = _insert_places(
            connection, snapshot, source_id, confidence_annotations
        )
        assertions_added = _insert_assertions(
            connection,
            snapshot,
            source_id,
            canonical_ids,
            place_ids,
            confidence_annotations,
        )
        assertions_added += place_assertions_added
        relationships_added = _insert_relationships(
            connection,
            snapshot,
            source_id,
            canonical_ids,
            confidence_annotations,
        )
        quarantine_working_conflicts(connection)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    return IngestResult(
        snapshot.snapshot_id,
        people_added,
        assertions_added,
        relationships_added,
    )
