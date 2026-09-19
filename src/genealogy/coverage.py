"""Cohort-scoped coverage and anomaly reporting from current conclusions."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from genealogy.cohorts import COHORT_CODES


EVIDENCE_FLOOR = "accepted_working"


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    """One explicit coverage denominator for a cohort."""

    name: str
    eligible: int
    included: int
    unknown: int
    cohort: str
    evidence_floor: str
    unit: str = "people"

    def __post_init__(self) -> None:
        if min(self.eligible, self.included, self.unknown) < 0:
            raise ValueError("coverage counts cannot be negative")
        if self.included + self.unknown != self.eligible:
            raise ValueError("included plus unknown must equal eligible")
        if self.unit not in {"people", "parent_edges"}:
            raise ValueError(f"unknown coverage unit {self.unit}")


@dataclass(frozen=True, slots=True)
class SnapshotAcquisition:
    """Aggregate source counts for one immutable RootsMagic acquisition."""

    snapshot_id: str
    people: int
    families: int
    child_links: int
    events: int
    places: int


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Deterministically ordered aggregate coverage for one cohort."""

    cohort: str
    evidence_floor: str
    metrics: tuple[CoverageMetric, ...]
    anomalies: dict[str, int]
    snapshot_acquisitions: tuple[SnapshotAcquisition, ...]

    def metric(self, name: str) -> CoverageMetric:
        aliases = {
            "accepted_parent_edge": "accepted_parent_edges",
            "citation": "citations",
            "known_child_set": "known_child_sets",
            "name": "primary_names",
            "note": "notes",
            "primary_name": "primary_names",
            "raw_place": "raw_places",
        }
        requested_name = aliases.get(name, name)
        for metric in self.metrics:
            if metric.name == requested_name:
                return metric
        raise KeyError(name)


def _person_ids(
    connection: sqlite3.Connection, cohort: str
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT person_id
        FROM cohort_membership
        WHERE cohort_code = ?
        ORDER BY person_id
        """,
        (cohort,),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _snapshot_acquisitions(
    connection: sqlite3.Connection,
) -> tuple[SnapshotAcquisition, ...]:
    rows = connection.execute(
        """
        SELECT
            snapshot_id,
            source_person_count,
            source_family_count,
            source_child_link_count,
            source_event_count,
            source_place_count
        FROM snapshot
        WHERE source_system = 'rootsmagic'
        ORDER BY snapshot_id
        """
    ).fetchall()
    return tuple(
        SnapshotAcquisition(
            snapshot_id=str(row[0]),
            people=int(row[1]),
            families=int(row[2]),
            child_links=int(row[3]),
            events=int(row[4]),
            places=int(row[5]),
        )
        for row in rows
    )


def _accepted_fact_rows(
    connection: sqlite3.Connection, cohort: str
) -> tuple[sqlite3.Row | tuple[object, ...], ...]:
    rows = connection.execute(
        """
        SELECT
            assertion.subject_person_id,
            assertion.predicate,
            assertion.value_text,
            assertion.place_id,
            source.citation_text,
            event.date_parse_status,
            event.note,
            place.raw_text,
            place.latitude,
            place.longitude,
            place.normalization_confidence,
            EXISTS (
                SELECT 1
                FROM conclusion AS place_current
                JOIN assertion AS place_assertion
                  ON place_assertion.assertion_id =
                     place_current.chosen_assertion_id
                WHERE place_assertion.place_id = assertion.place_id
                  AND place_assertion.predicate = 'place.raw_text'
                  AND place_current.predicate =
                      place_assertion.predicate
                  AND place_current.confidence = ?
            ) AS place_is_accepted
        FROM conclusion AS current
        JOIN assertion AS assertion
          ON assertion.assertion_id = current.chosen_assertion_id
        JOIN cohort_membership AS membership
          ON membership.person_id = assertion.subject_person_id
         AND membership.cohort_code = ?
        JOIN source AS source
          ON source.source_id = assertion.source_id
        LEFT JOIN event_observation AS event
          ON event.assertion_id = assertion.assertion_id
        LEFT JOIN place AS place
          ON place.place_id = assertion.place_id
        WHERE current.confidence = ?
          AND current.predicate = assertion.predicate
        ORDER BY assertion.assertion_id
        """,
        (EVIDENCE_FLOOR, cohort, EVIDENCE_FLOOR),
    ).fetchall()
    return tuple(rows)


def _relationship_metric(
    connection: sqlite3.Connection, cohort: str
) -> tuple[int, int]:
    row = connection.execute(
        """
        WITH canonical_edges AS (
            SELECT
                relationship.subject_person_id,
                relationship.object_person_id,
                relationship.predicate,
                relationship.role,
                max(
                    CASE WHEN current.confidence = ? THEN 1 ELSE 0 END
                ) AS is_included
            FROM conclusion AS current
            JOIN relationship_assertion AS relationship
              ON relationship.relationship_assertion_id =
                 current.chosen_relationship_assertion_id
            JOIN cohort_membership AS membership
              ON membership.person_id = relationship.object_person_id
             AND membership.cohort_code = ?
            WHERE current.predicate = relationship.predicate
              AND relationship.predicate = 'parent_child'
            GROUP BY
                relationship.subject_person_id,
                relationship.object_person_id,
                relationship.predicate,
                relationship.role
        )
        SELECT
            count(*) AS eligible,
            coalesce(sum(is_included), 0) AS included
        FROM canonical_edges
        """,
        (EVIDENCE_FLOOR, cohort),
    ).fetchone()
    return int(row[0]), int(row[1])


def _known_parent_ids(
    connection: sqlite3.Connection, cohort: str
) -> set[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT relationship.subject_person_id
        FROM conclusion AS current
        JOIN relationship_assertion AS relationship
          ON relationship.relationship_assertion_id =
             current.chosen_relationship_assertion_id
        JOIN cohort_membership AS membership
          ON membership.person_id = relationship.subject_person_id
         AND membership.cohort_code = ?
        WHERE current.confidence = ?
          AND current.predicate = relationship.predicate
          AND relationship.predicate = 'parent_child'
        """,
        (cohort, EVIDENCE_FLOOR),
    ).fetchall()
    return {row[0] for row in rows}


def _anomalies(
    connection: sqlite3.Connection, cohort: str
) -> dict[str, int]:
    unparsed_dates = connection.execute(
        """
        SELECT count(*)
        FROM conclusion AS current
        JOIN assertion AS assertion
          ON assertion.assertion_id = current.chosen_assertion_id
        JOIN event_observation AS event
          ON event.assertion_id = assertion.assertion_id
        JOIN cohort_membership AS membership
          ON membership.person_id = assertion.subject_person_id
         AND membership.cohort_code = ?
        WHERE current.predicate = assertion.predicate
          AND event.date_parse_status = 'unparsed'
        """,
        (cohort,),
    ).fetchone()[0]
    duplicate_external_ids = connection.execute(
        """
        SELECT count(*)
        FROM (
            SELECT lower(observation.system), observation.value
            FROM person_identifier_observation AS observation
            JOIN cohort_membership AS membership
              ON membership.person_id = observation.person_id
             AND membership.cohort_code = ?
            GROUP BY lower(observation.system), observation.value
            HAVING count(DISTINCT observation.person_id) > 1
        )
        """,
        (cohort,),
    ).fetchone()[0]
    quarantined_edges = connection.execute(
        """
        SELECT count(*)
        FROM conclusion AS current
        JOIN relationship_assertion AS relationship
          ON relationship.relationship_assertion_id =
             current.chosen_relationship_assertion_id
        WHERE current.predicate = relationship.predicate
          AND current.confidence = 'quarantined_contradiction'
          AND (
              EXISTS (
                  SELECT 1
                  FROM cohort_membership AS membership
                  WHERE membership.person_id =
                        relationship.subject_person_id
                    AND membership.cohort_code = ?
              )
              OR EXISTS (
                  SELECT 1
                  FROM cohort_membership AS membership
                  WHERE membership.person_id =
                        relationship.object_person_id
                    AND membership.cohort_code = ?
              )
          )
        """,
        (cohort, cohort),
    ).fetchone()[0]
    return {
        "duplicate_external_id": int(duplicate_external_ids),
        "quarantined_relationship_edge": int(quarantined_edges),
        "unparsed_date": int(unparsed_dates),
    }


def build_coverage_report(
    connection: sqlite3.Connection, cohort: str
) -> CoverageReport:
    """Build aggregate coverage using current accepted working conclusions."""
    if cohort not in COHORT_CODES:
        raise ValueError(f"unknown cohort {cohort}")

    person_ids = _person_ids(connection, cohort)
    eligible_people = len(person_ids)
    accepted_rows = _accepted_fact_rows(connection, cohort)
    names: set[str] = set()
    births: set[str] = set()
    deaths: set[str] = set()
    raw_places: set[str] = set()
    resolved_coordinates: set[str] = set()
    citations: set[str] = set()
    notes: set[str] = set()

    for row in accepted_rows:
        (
            person_id,
            predicate,
            value_text,
            place_id,
            citation_text,
            parse_status,
            note,
            raw_place,
            latitude,
            longitude,
            normalization_confidence,
            place_is_accepted,
        ) = row
        if (
            predicate == "person.primary_name"
            and value_text is not None
            and str(value_text).strip()
        ):
            names.add(str(person_id))
        if predicate == "event.birth" and parse_status == "parsed":
            births.add(str(person_id))
        if predicate == "event.death" and parse_status == "parsed":
            deaths.add(str(person_id))
        if (
            place_id is not None
            and place_is_accepted
            and raw_place is not None
            and str(raw_place).strip()
        ):
            raw_places.add(str(person_id))
        if (
            place_id is not None
            and place_is_accepted
            and latitude is not None
            and longitude is not None
            and normalization_confidence == EVIDENCE_FLOOR
        ):
            resolved_coordinates.add(str(person_id))
        if citation_text is not None and str(citation_text).strip():
            citations.add(str(person_id))
        if note is not None and str(note).strip():
            notes.add(str(person_id))

    familysearch_ids = {
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT identifier.person_id
            FROM person_identifier AS identifier
            JOIN cohort_membership AS membership
              ON membership.person_id = identifier.person_id
             AND membership.cohort_code = ?
            WHERE lower(identifier.system) = 'familysearch'
              AND length(trim(identifier.value)) > 0
            """,
            (cohort,),
        ).fetchall()
    }
    known_child_sets = _known_parent_ids(connection, cohort)
    parent_eligible, parent_included = _relationship_metric(
        connection, cohort
    )

    def person_metric(name: str, included_people: set[str]) -> CoverageMetric:
        included = len(included_people)
        return CoverageMetric(
            name=name,
            eligible=eligible_people,
            included=included,
            unknown=eligible_people - included,
            cohort=cohort,
            evidence_floor=EVIDENCE_FLOOR,
        )

    metrics = (
        person_metric("birth_date", births),
        person_metric("citations", citations),
        person_metric("death_date", deaths),
        person_metric("familysearch_id", familysearch_ids),
        person_metric("known_child_sets", known_child_sets),
        person_metric("notes", notes),
        person_metric("people", set(person_ids)),
        person_metric("primary_names", names),
        person_metric("raw_places", raw_places),
        person_metric("recorded_lifespan", births & deaths),
        person_metric("resolved_coordinates", resolved_coordinates),
        CoverageMetric(
            name="accepted_parent_edges",
            eligible=parent_eligible,
            included=parent_included,
            unknown=parent_eligible - parent_included,
            cohort=cohort,
            evidence_floor=EVIDENCE_FLOOR,
            unit="parent_edges",
        ),
    )
    return CoverageReport(
        cohort=cohort,
        evidence_floor=EVIDENCE_FLOOR,
        metrics=tuple(sorted(metrics, key=lambda metric: metric.name)),
        anomalies=dict(sorted(_anomalies(connection, cohort).items())),
        snapshot_acquisitions=_snapshot_acquisitions(connection),
    )
