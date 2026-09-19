"""Deterministic cohorts derived from current accepted relationships."""

from dataclasses import dataclass
import sqlite3


COHORT_CODES = ("A", "B", "C", "D", "Z")


@dataclass(frozen=True, slots=True)
class CohortResult:
    """The sorted memberships produced by one atomic recomputation."""

    root_person_id: str
    memberships: dict[str, tuple[str, ...]]


_ACCEPTED_RELATIONSHIPS = """
    SELECT
        relationship.subject_person_id,
        relationship.predicate,
        relationship.object_person_id,
        relationship.snapshot_id,
        relationship.raw_external_family_id
    FROM relationship_assertion AS relationship
    JOIN conclusion AS current
      ON current.chosen_relationship_assertion_id =
         relationship.relationship_assertion_id
    WHERE current.confidence = 'accepted_working'
      AND current.predicate = relationship.predicate
"""


def _ancestor_ids(
    connection: sqlite3.Connection, root_person_id: str
) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        WITH RECURSIVE
        accepted_relationship AS ({_ACCEPTED_RELATIONSHIPS}),
        ancestor(person_id) AS (
            SELECT subject_person_id
            FROM accepted_relationship
            WHERE predicate = 'parent_child'
              AND object_person_id = ?
            UNION
            SELECT accepted.subject_person_id
            FROM accepted_relationship AS accepted
            JOIN ancestor
              ON accepted.object_person_id = ancestor.person_id
            WHERE accepted.predicate = 'parent_child'
        )
        SELECT person_id
        FROM ancestor
        WHERE person_id != ?
        ORDER BY person_id
        """,
        (root_person_id, root_person_id),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _ancestral_family_units(
    connection: sqlite3.Connection,
    lineage_children: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    if not lineage_children:
        return ()
    placeholders = ", ".join("?" for _ in lineage_children)
    rows = connection.execute(
        f"""
        WITH accepted_relationship AS ({_ACCEPTED_RELATIONSHIPS})
        SELECT snapshot_id, raw_external_family_id
        FROM accepted_relationship
        WHERE predicate = 'parent_child'
          AND object_person_id IN ({placeholders})
        GROUP BY snapshot_id, raw_external_family_id, object_person_id
        HAVING count(DISTINCT subject_person_id) >= 2
        ORDER BY snapshot_id, raw_external_family_id
        """,
        lineage_children,
    ).fetchall()
    return tuple((row[0], row[1]) for row in rows)


def _children_of_families(
    connection: sqlite3.Connection,
    family_units: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    if not family_units:
        return ()
    values = ", ".join("(?, ?)" for _ in family_units)
    parameters = tuple(
        value for family_unit in family_units for value in family_unit
    )
    rows = connection.execute(
        f"""
        WITH
        accepted_relationship AS ({_ACCEPTED_RELATIONSHIPS}),
        ancestral_family(snapshot_id, family_id) AS (VALUES {values})
        SELECT DISTINCT accepted.object_person_id
        FROM accepted_relationship AS accepted
        JOIN ancestral_family
          ON ancestral_family.snapshot_id = accepted.snapshot_id
         AND ancestral_family.family_id =
             accepted.raw_external_family_id
        WHERE accepted.predicate = 'parent_child'
        ORDER BY accepted.object_person_id
        """,
        parameters,
    ).fetchall()
    return tuple(row[0] for row in rows)


def _spouses_of(
    connection: sqlite3.Connection, person_ids: tuple[str, ...]
) -> tuple[str, ...]:
    if not person_ids:
        return ()
    placeholders = ", ".join("?" for _ in person_ids)
    rows = connection.execute(
        f"""
        WITH accepted_relationship AS ({_ACCEPTED_RELATIONSHIPS})
        SELECT object_person_id
        FROM accepted_relationship
        WHERE predicate = 'spouse'
          AND subject_person_id IN ({placeholders})
        UNION
        SELECT subject_person_id
        FROM accepted_relationship
        WHERE predicate = 'spouse'
          AND object_person_id IN ({placeholders})
        ORDER BY 1
        """,
        (*person_ids, *person_ids),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _store_derived_memberships(
    connection: sqlite3.Connection,
    root_person_id: str,
    memberships: dict[str, tuple[str, ...]],
) -> None:
    reasons = {
        "A": f"Current accepted ancestor of root person {root_person_id}",
        "B": "Child of a current accepted ancestor",
        "C": "Spouse of a cohort B person outside cohorts A and B",
        "Z": "Background imported person outside cohorts A through D",
    }
    methods = {"A": "computed", "B": "computed", "C": "computed", "Z": "background"}
    connection.execute(
        "DELETE FROM cohort_membership WHERE cohort_code IN ('A', 'B', 'C', 'Z')"
    )
    connection.execute(
        """
        DELETE FROM cohort_membership
        WHERE cohort_code = 'D'
          AND (
              derivation_method != 'curated'
              OR length(trim(inclusion_reason)) = 0
          )
        """
    )
    for cohort_code in ("A", "B", "C", "Z"):
        connection.executemany(
            """
            INSERT INTO cohort_membership(
                person_id, cohort_code, inclusion_reason, derivation_method
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (
                    person_id,
                    cohort_code,
                    reasons[cohort_code],
                    methods[cohort_code],
                )
                for person_id in memberships[cohort_code]
            ),
        )


def recompute_cohorts(
    connection: sqlite3.Connection, root_person_id: str
) -> CohortResult:
    """Atomically replace derived cohorts from current accepted conclusions."""
    if connection.execute(
        "SELECT 1 FROM person WHERE person_id = ?", (root_person_id,)
    ).fetchone() is None:
        raise ValueError(f"unknown root person {root_person_id}")
    if connection.in_transaction:
        raise sqlite3.ProgrammingError(
            "recompute_cohorts requires a connection without an active transaction"
        )

    connection.execute("BEGIN IMMEDIATE")
    try:
        ancestors = _ancestor_ids(connection, root_person_id)
        ancestral_families = _ancestral_family_units(
            connection, (root_person_id, *ancestors)
        )
        children = _children_of_families(
            connection, ancestral_families
        )
        ancestor_or_child = set(ancestors) | set(children)
        spouses = tuple(
            person_id
            for person_id in _spouses_of(connection, children)
            if person_id not in ancestor_or_child
        )
        curated = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT person_id
                FROM cohort_membership
                WHERE cohort_code = 'D'
                  AND derivation_method = 'curated'
                  AND length(trim(inclusion_reason)) > 0
                ORDER BY person_id
                """
            ).fetchall()
        )
        included = ancestor_or_child | set(spouses) | set(curated)
        background = tuple(
            row[0]
            for row in connection.execute(
                "SELECT person_id FROM person ORDER BY person_id"
            ).fetchall()
            if row[0] not in included
        )
        memberships = {
            "A": ancestors,
            "B": children,
            "C": spouses,
            "D": curated,
            "Z": background,
        }
        _store_derived_memberships(
            connection, root_person_id, memberships
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return CohortResult(root_person_id, memberships)
