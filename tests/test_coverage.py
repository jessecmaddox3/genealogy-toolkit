"""Cohort-scoped coverage, anomaly, and safe rendering tests."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from genealogy.coverage import build_coverage_report
from genealogy.render import render_coverage_json, render_coverage_markdown
from genealogy.store import create_store


PRIVATE_MARKERS = (
    "PRIVATE-SEED-NAME",
    "17 Jan 1986",
    "private-secret",
)


def _add_assertion(
    connection: sqlite3.Connection,
    *,
    person_id: str,
    predicate: str,
    source_id: int,
    raw_id: str,
    confidence: str = "accepted_working",
    value_text: str | None = None,
    raw_value: str | None = None,
    place_id: int | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO assertion(
            subject_type, subject_id, subject_person_id, predicate,
            value_text, raw_value, snapshot_id, source_id, place_id,
            raw_external_assertion_id, raw_external_owner_id
        ) VALUES ('person', ?, ?, ?, ?, ?, 'snapshot-1', ?, ?, ?, ?)
        """,
        (
            person_id,
            person_id,
            predicate,
            value_text,
            raw_value,
            source_id,
            place_id,
            raw_id,
            person_id,
        ),
    )
    assertion_id = cursor.lastrowid
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            confidence, rationale
        ) VALUES ('person', ?, ?, ?, ?, 'coverage fixture')
        """,
        (person_id, predicate, assertion_id, confidence),
    )
    return assertion_id


def _add_event(
    connection: sqlite3.Connection,
    *,
    person_id: str,
    predicate: str,
    source_id: int,
    ordinal: int,
    parse_status: str,
    raw_date: str,
    place_id: int | None = None,
    note: str = "",
) -> None:
    assertion_id = _add_assertion(
        connection,
        person_id=person_id,
        predicate=predicate,
        source_id=source_id,
        raw_id=f"event-{ordinal}",
        raw_value=raw_date,
        place_id=place_id,
    )
    fact_name = "Birth" if predicate == "event.birth" else "Death"
    connection.execute(
        """
        INSERT INTO event_observation(
            snapshot_id, observation_ordinal, assertion_id, person_id,
            place_id, external_event_id, owner_type, external_owner_id,
            fact_type_id, fact_type_name, raw_date, date_modifier,
            date_start_year, date_parse_status, details, note, private
        ) VALUES (
            'snapshot-1', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?,
            ?, ?, '', ?, 0
        )
        """,
        (
            ordinal,
            assertion_id,
            person_id,
            place_id,
            str(ordinal),
            person_id,
            predicate,
            fact_name,
            raw_date,
            "exact" if parse_status == "parsed" else "unknown",
            1900 if parse_status == "parsed" else None,
            parse_status,
            note,
        ),
    )


def _add_relationship(
    connection: sqlite3.Connection,
    *,
    parent_id: str,
    child_id: str,
    source_id: int,
    raw_id: str,
    confidence: str,
    role: str = "parent",
    snapshot_id: str = "snapshot-1",
) -> None:
    cursor = connection.execute(
        """
        INSERT INTO relationship_assertion(
            subject_person_id, predicate, object_person_id, role,
            snapshot_id, source_id, raw_external_relationship_id,
            raw_external_family_id
        ) VALUES (?, 'parent_child', ?, ?, ?, ?, ?, ?)
        """,
        (
            parent_id,
            child_id,
            role,
            snapshot_id,
            source_id,
            raw_id,
            f"family-{raw_id}",
        ),
    )
    relationship_id = cursor.lastrowid
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES (
            'relationship', ?, 'parent_child', ?, ?, 'coverage fixture'
        )
        """,
        (str(relationship_id), relationship_id, confidence),
    )


def _add_place_conclusion(
    connection: sqlite3.Connection,
    *,
    place_id: int,
    source_id: int,
    raw_id: str,
) -> None:
    assertion_id = connection.execute(
        """
        INSERT INTO assertion(
            subject_type, subject_id, predicate, value_text, raw_value,
            snapshot_id, source_id, place_id, raw_external_assertion_id,
            raw_external_owner_id, raw_external_place_id
        ) VALUES (
            'place', ?, 'place.raw_text', 'fixture place', 'fixture place',
            'snapshot-1', ?, ?, ?, ?, ?
        )
        """,
        (str(place_id), source_id, place_id, raw_id, raw_id, raw_id),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            confidence, rationale
        ) VALUES (
            'place', ?, 'place.raw_text', ?,
            'accepted_working', 'coverage fixture'
        )
        """,
        (str(place_id), assertion_id),
    )


@pytest.fixture
def store_with_cohorts(tmp_path: Path) -> sqlite3.Connection:
    connection = create_store(tmp_path / "coverage.sqlite")
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES ('snapshot-1', 'abc', 'test', 5, 3, 3, 6, 2)
        """
    )
    cited_source = connection.execute(
        """
        INSERT INTO source(
            snapshot_id, source_type, record_title, evidence_tier,
            citation_text
        ) VALUES (
            'snapshot-1', 'test', 'Cited fixture', 'original_record',
            'private-secret citation'
        )
        """
    ).lastrowid
    uncited_source = connection.execute(
        """
        INSERT INTO source(
            snapshot_id, source_type, record_title, evidence_tier
        ) VALUES (
            'snapshot-1', 'test', 'Uncited fixture', 'tree_aggregate'
        )
        """
    ).lastrowid

    for person_id, cohort in (
        ("p1", "A"),
        ("p2", "A"),
        ("p3", "A"),
        ("p4", "A"),
        ("outside", "Z"),
    ):
        connection.execute(
            "INSERT INTO person(person_id, living, private) VALUES (?, ?, ?)",
            (person_id, person_id == "p1", person_id == "p1"),
        )
        connection.execute(
            """
            INSERT INTO cohort_membership(
                person_id, cohort_code, inclusion_reason, derivation_method
            ) VALUES (?, ?, 'coverage fixture', 'curated')
            """,
            (person_id, cohort),
        )

    resolved_place = connection.execute(
        """
        INSERT INTO place(
            snapshot_id, raw_external_place_id, raw_text, latitude,
            longitude, normalization_confidence
        ) VALUES (
            'snapshot-1', 'place-1', 'Private birthplace',
            33.7, -84.4, 'accepted_working'
        )
        """
    ).lastrowid
    raw_place = connection.execute(
        """
        INSERT INTO place(
            snapshot_id, raw_external_place_id, raw_text
        ) VALUES ('snapshot-1', 'place-2', 'Unresolved place')
        """
    ).lastrowid
    _add_place_conclusion(
        connection,
        place_id=resolved_place,
        source_id=cited_source,
        raw_id="place-1",
    )
    _add_place_conclusion(
        connection,
        place_id=raw_place,
        source_id=uncited_source,
        raw_id="place-2",
    )

    _add_assertion(
        connection,
        person_id="p1",
        predicate="person.primary_name",
        source_id=cited_source,
        raw_id="name-1",
        value_text="PRIVATE-SEED-NAME",
    )
    _add_assertion(
        connection,
        person_id="p2",
        predicate="person.primary_name",
        source_id=uncited_source,
        raw_id="name-2",
        value_text="Second Person",
    )
    _add_assertion(
        connection,
        person_id="p3",
        predicate="person.primary_name",
        source_id=cited_source,
        raw_id="name-3",
        value_text="Quarantined Name",
        confidence="quarantined_contradiction",
    )

    _add_event(
        connection,
        person_id="p1",
        predicate="event.birth",
        source_id=cited_source,
        ordinal=1,
        parse_status="parsed",
        raw_date="17 Jan 1986",
        place_id=resolved_place,
        note="private-secret note",
    )
    _add_event(
        connection,
        person_id="p1",
        predicate="event.death",
        source_id=cited_source,
        ordinal=2,
        parse_status="parsed",
        raw_date="D.+20500101..+00000000..",
    )
    _add_event(
        connection,
        person_id="p2",
        predicate="event.birth",
        source_id=uncited_source,
        ordinal=3,
        parse_status="unparsed",
        raw_date="not-a-date",
        place_id=raw_place,
    )
    _add_event(
        connection,
        person_id="p2",
        predicate="event.death",
        source_id=uncited_source,
        ordinal=4,
        parse_status="parsed",
        raw_date="D.+19700101..+00000000..",
    )
    _add_event(
        connection,
        person_id="p3",
        predicate="event.birth",
        source_id=cited_source,
        ordinal=5,
        parse_status="parsed",
        raw_date="D.+19000101..+00000000..",
    )
    _add_event(
        connection,
        person_id="p3",
        predicate="event.death",
        source_id=cited_source,
        ordinal=6,
        parse_status="parsed",
        raw_date="D.+19800101..+00000000..",
    )

    for person_id, value in (("p1", "AAAA-111"), ("p2", "BBBB-222")):
        connection.execute(
            """
            INSERT INTO person_identifier(
                person_id, system, value, first_seen_snapshot_id,
                last_seen_snapshot_id
            ) VALUES (?, 'familysearch', ?, 'snapshot-1', 'snapshot-1')
            """,
            (person_id, value),
        )

    duplicated_identifier_id = connection.execute(
        """
        INSERT INTO person_identifier(
            person_id, system, value, scope_snapshot_id,
            first_seen_snapshot_id, last_seen_snapshot_id
        ) VALUES (
            'p1', 'legacy', 'duplicate-7', 'snapshot-1',
            'snapshot-1', 'snapshot-1'
        )
        """
    ).lastrowid
    for ordinal, (person_id, system) in enumerate(
        (("p1", "Legacy"), ("p2", "legacy")), start=20
    ):
        connection.execute(
            """
            INSERT INTO person_identifier_observation(
                snapshot_id, observation_ordinal, person_identifier_id,
                person_id, external_person_id, system, value, source_link_id
            ) VALUES (
                'snapshot-1', ?, ?, ?, ?, ?, 'duplicate-7', ?
            )
            """,
            (
                ordinal,
                duplicated_identifier_id,
                person_id,
                person_id,
                system,
                f"duplicate-link-{ordinal}",
            ),
        )

    _add_relationship(
        connection,
        parent_id="p1",
        child_id="p4",
        source_id=cited_source,
        raw_id="accepted-1",
        confidence="accepted_working",
    )
    _add_relationship(
        connection,
        parent_id="p3",
        child_id="p4",
        source_id=cited_source,
        raw_id="accepted-2",
        confidence="accepted_working",
    )
    _add_relationship(
        connection,
        parent_id="p2",
        child_id="p3",
        source_id=uncited_source,
        raw_id="quarantined-1",
        confidence="quarantined_contradiction",
    )
    _add_relationship(
        connection,
        parent_id="outside",
        child_id="outside",
        source_id=uncited_source,
        raw_id="outside-quarantine",
        confidence="quarantined_contradiction",
    )
    return connection


def test_person_metric_families_keep_explicit_unknown_denominators(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """Dropping missing or unparsed cohort people must break every denominator."""
    report = build_coverage_report(store_with_cohorts, "A")
    actual = {
        metric.name: (metric.eligible, metric.included, metric.unknown)
        for metric in report.metrics
        if metric.name != "accepted_parent_edges"
    }

    assert actual == {
        "birth_date": (4, 2, 2),
        "citations": (4, 2, 2),
        "death_date": (4, 3, 1),
        "familysearch_id": (4, 2, 2),
        "known_child_sets": (4, 2, 2),
        "notes": (4, 1, 3),
        "people": (4, 4, 0),
        "primary_names": (4, 2, 2),
        "raw_places": (4, 2, 2),
        "recorded_lifespan": (4, 2, 2),
        "resolved_coordinates": (4, 1, 3),
    }
    assert all(metric.cohort == "A" for metric in report.metrics)
    assert all(
        metric.evidence_floor == "accepted_working"
        for metric in report.metrics
    )


def test_relationships_and_anomalies_use_current_cohort_scoped_conclusions(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """Raw, quarantined, or out-of-cohort edges must not count as accepted."""
    report = build_coverage_report(store_with_cohorts, "A")

    assert report.metric("accepted_parent_edges").eligible == 3
    assert report.metric("accepted_parent_edges").included == 2
    assert report.metric("accepted_parent_edges").unknown == 1
    assert report.anomalies == {
        "duplicate_external_id": 1,
        "quarantined_relationship_edge": 1,
        "unparsed_date": 1,
    }


def test_overlapping_snapshot_claims_count_distinct_canonical_parent_edges(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """Duplicate claims must collapse, while endpoint and role changes must not."""
    store_with_cohorts.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES ('snapshot-2', 'def', 'test', 0, 0, 0, 0, 0)
        """
    )
    source_id = store_with_cohorts.execute(
        """
        INSERT INTO source(
            snapshot_id, source_type, record_title, evidence_tier
        ) VALUES (
            'snapshot-2', 'test', 'Overlapping fixture', 'tree_aggregate'
        )
        """
    ).lastrowid
    _add_relationship(
        store_with_cohorts,
        parent_id="p1",
        child_id="p4",
        source_id=source_id,
        raw_id="duplicate-accepted",
        confidence="accepted_working",
        snapshot_id="snapshot-2",
    )
    _add_relationship(
        store_with_cohorts,
        parent_id="p1",
        child_id="p4",
        source_id=source_id,
        raw_id="distinct-role",
        confidence="accepted_working",
        role="father",
        snapshot_id="snapshot-2",
    )
    _add_relationship(
        store_with_cohorts,
        parent_id="p2",
        child_id="p4",
        source_id=source_id,
        raw_id="distinct-edge",
        confidence="accepted_working",
        snapshot_id="snapshot-2",
    )

    report = build_coverage_report(store_with_cohorts, "A")
    metric = report.metric("accepted_parent_edges")

    assert store_with_cohorts.execute(
        "SELECT count(*) FROM relationship_assertion"
    ).fetchone()[0] == 7
    assert (metric.eligible, metric.included, metric.unknown) == (5, 4, 1)
    assert metric.unit == "parent_edges"


def test_metric_units_keep_people_separate_from_parent_edges(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """Removing units or labeling edge denominators as people must fail."""
    report = build_coverage_report(store_with_cohorts, "A")
    units = {metric.name: metric.unit for metric in report.metrics}

    assert units == {
        "accepted_parent_edges": "parent_edges",
        "birth_date": "people",
        "citations": "people",
        "death_date": "people",
        "familysearch_id": "people",
        "known_child_sets": "people",
        "notes": "people",
        "people": "people",
        "primary_names": "people",
        "raw_places": "people",
        "recorded_lifespan": "people",
        "resolved_coordinates": "people",
    }


def test_place_coverage_requires_an_accepted_current_place_conclusion(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """A quarantined place must not be usable through an accepted event."""
    store_with_cohorts.execute(
        """
        UPDATE conclusion
        SET confidence = 'quarantined_contradiction'
        WHERE predicate = 'place.raw_text'
          AND subject_id = (
              SELECT CAST(place_id AS TEXT)
              FROM place
              WHERE raw_external_place_id = 'place-2'
          )
        """
    )

    metric = build_coverage_report(store_with_cohorts, "A").metric(
        "raw_places"
    )

    assert (metric.eligible, metric.included, metric.unknown) == (4, 1, 3)


def test_renderers_are_deterministic_aggregate_only_and_newline_terminated(
    store_with_cohorts: sqlite3.Connection,
) -> None:
    """Including private values, unstable ordering, or partial JSON must fail."""
    report = build_coverage_report(store_with_cohorts, "A")

    markdown_first = render_coverage_markdown(report)
    markdown_second = render_coverage_markdown(report)
    json_first = render_coverage_json(report)
    json_second = render_coverage_json(report)

    assert markdown_first == markdown_second
    assert json_first == json_second
    assert markdown_first.startswith("# TL;DR\n")
    assert "Eligible people: 4" in markdown_first
    assert "- parent_edges: 1 metric, 3 eligible" in markdown_first
    assert "- people: 11 metrics, 4 eligible" in markdown_first
    assert "Included metric values" not in markdown_first
    assert "Unknown metric values" not in markdown_first
    assert "| Metric | Unit | Eligible |" in markdown_first
    assert json_first.endswith("\n")
    payload = json.loads(json_first)
    assert payload["summary"] == {
        "anomaly_type_count": 3,
        "coverage_units": {
            "parent_edges": {"eligible": 3, "metric_count": 1},
            "people": {"eligible": 4, "metric_count": 11},
        },
        "eligible_people": 4,
        "metric_count": 12,
    }
    assert "anomaly_count" not in payload["summary"]
    assert "included_metric_values" not in payload["summary"]
    assert "unknown_metric_values" not in payload["summary"]
    assert list(payload["anomalies"]) == sorted(payload["anomalies"])
    assert [item["name"] for item in payload["metrics"]] == sorted(
        item["name"] for item in payload["metrics"]
    )
    assert {item["unit"] for item in payload["metrics"]} == {
        "parent_edges",
        "people",
    }
    for marker in PRIVATE_MARKERS:
        assert marker not in markdown_first
        assert marker not in json_first
    assert "\N{EM DASH}" not in markdown_first


def test_coverage_lists_rootsmagic_snapshot_acquisition_counts(store_with_cohorts: sqlite3.Connection) -> None:
    """Two independently invented acquisitions keep separate denominators."""
    acquisitions = [
        ("synthetic-amber-2037-04-09", "demo-amber", 23, 8, 11, 41, 7),
        ("synthetic-violet-2038-11-02", "demo-violet", 17, 6, 9, 29, 5),
    ]
    store_with_cohorts.executemany("""
        INSERT INTO snapshot(snapshot_id, manifest_sha256, source_system,
          source_person_count, source_family_count, source_child_link_count, source_event_count, source_place_count)
        VALUES (?, ?, 'rootsmagic', ?, ?, ?, ?, ?)
    """, acquisitions)
    report = build_coverage_report(store_with_cohorts, "A")
    assert [item.people for item in report.snapshot_acquisitions] == [23, 17]
    assert json.loads(render_coverage_json(report))["snapshot_acquisitions"] == [
        {"snapshot_id": "synthetic-amber-2037-04-09", "people": 23, "families": 8, "child_links": 11, "events": 41, "places": 7},
        {"snapshot_id": "synthetic-violet-2038-11-02", "people": 17, "families": 6, "child_links": 9, "events": 29, "places": 5},
    ]
    assert "## Snapshot acquisitions" in render_coverage_markdown(report)


def test_generated_reports_are_ignored_but_gitkeep_is_trackable(tmp_path: Path) -> None:
    """Dropping the generated-report ignore boundary must fail Git behavior."""
    source = Path(__file__).resolve().parents[1]
    repository = tmp_path / "isolated-repository"
    repository.mkdir()
    (repository / ".gitignore").write_text((source / ".gitignore").read_text())
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)

    generated = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            "reports/generated/coverage.md",
        ],
        cwd=repository,
        check=False,
    )
    gitkeep = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            "reports/generated/.gitkeep",
        ],
        cwd=repository,
        check=False,
    )

    assert generated.returncode == 0
    assert gitkeep.returncode == 1
