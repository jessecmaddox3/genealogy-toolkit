from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import uuid

import pytest

from genealogy.identity import add_global_identifier
from genealogy.research_records import (
    ResearchBatchValidationError,
    load_research_batch,
)
from genealogy.research_store import ingest_research_batch
from genealogy.rm_reader import extract_snapshot
from genealogy.store import SnapshotConflictError, create_store, ingest_snapshot
from tests.fixtures.research_batch import write_research_batch_fixture
from tests.fixtures.rm_fixture import build_rm_fixture


def test_source_file_schema_enforces_hash_rights_and_status(tmp_path: Path) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(source_file)")
    }
    assert columns == {
        "source_file_id",
        "sha256",
        "size_bytes",
        "local_path",
        "original_filename",
        "rights_label",
        "ocr_status",
        "transcription_status",
        "created_at",
    }
    link_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(source_file_link)")
    }
    assert link_columns == {
        "source_file_link_id",
        "source_file_id",
        "source_id",
    }
    source_key_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(research_source_key)"
        )
    }
    assert source_key_columns == {
        "snapshot_id",
        "source_key",
        "source_id",
    }
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO source_file_link(source_file_id, source_id)
            VALUES (999, 999)
            """
        )


def test_source_file_reuses_hash_through_distinct_source_links(
    tmp_path: Path,
) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    connection.execute(
        """
        INSERT INTO source(
            source_type, record_title, evidence_tier
        ) VALUES ('document', 'Fixture', 'original_record')
        """
    )
    first_source_id = connection.execute(
        "SELECT source_id FROM source"
    ).fetchone()[0]
    second_source_id = connection.execute(
        """
        INSERT INTO source(
            source_type, record_title, evidence_tier
        ) VALUES ('document', 'Second fixture', 'original_record')
        """
    ).lastrowid
    source_file_id = connection.execute(
        """
        INSERT INTO source_file(
            sha256, size_bytes, local_path,
            original_filename, rights_label, ocr_status,
            transcription_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "a" * 64,
            10,
            "data/private/fixture.pdf",
            "fixture.pdf",
            "personal_research",
            "not_started",
            "not_started",
        ),
    ).lastrowid
    connection.executemany(
        """
        INSERT INTO source_file_link(source_file_id, source_id)
        VALUES (?, ?)
        """,
        (
            (source_file_id, first_source_id),
            (source_file_id, second_source_id),
        ),
    )
    assert connection.execute(
        "SELECT count(*) FROM source_file"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM source_file_link"
    ).fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO source_file_link(source_file_id, source_id)
            VALUES (?, ?)
            """,
            (source_file_id, first_source_id),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("sha256", "ABC"),
        ("rights_label", "unknown"),
        ("ocr_status", "finished"),
        ("transcription_status", "finished"),
    ),
)
def test_source_file_rejects_invalid_controlled_values(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    fields = {
        "sha256": "b" * 64,
        "rights_label": "personal_research",
        "ocr_status": "not_started",
        "transcription_status": "not_started",
    }
    fields[column] = value
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO source_file(
                sha256, size_bytes, local_path, original_filename,
                rights_label, ocr_status, transcription_status
            ) VALUES (?, 1, 'data/private/file.pdf', 'file.pdf', ?, ?, ?)
            """,
            (
                fields["sha256"],
                fields["rights_label"],
                fields["ocr_status"],
                fields["transcription_status"],
            ),
        )


def test_research_question_title_is_unique(tmp_path: Path) -> None:
    connection = create_store(tmp_path / "genealogy.sqlite")
    connection.execute(
        """
        INSERT INTO research_question(title, status)
        VALUES ('Who were the example parents?', 'open')
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO research_question(title, status)
            VALUES ('Who were the example parents?', 'in_progress')
            """
        )


def _load_fixture_batch(tmp_path: Path):
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    return load_research_batch(batch_path)


def _write_fixture_record(tmp_path: Path, content: bytes = b"example estate bytes") -> Path:
    record = (
        tmp_path
        / "data"
        / "private"
        / "research"
        / "example-workshop.pdf"
    )
    record.parent.mkdir(parents=True)
    record.write_bytes(content)
    return record


def _add_exact_identity(
    connection: sqlite3.Connection,
    *,
    snapshot_id: str,
    system: str,
    value: str,
    person_id: str | None = None,
) -> str:
    person_id = str(uuid.uuid4()) if person_id is None else person_id
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
    connection.execute(
        "INSERT INTO person(person_id, living, private) VALUES (?, 0, 0)",
        (person_id,),
    )
    add_global_identifier(
        connection,
        person_id=person_id,
        system=system,
        value=value,
        snapshot_id=snapshot_id,
    )
    return person_id


def test_ingest_research_batch_writes_documentary_provenance(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")

    result = ingest_research_batch(connection, batch, tmp_path)

    assert result.repeated is False
    assert result.snapshot_id == "research-batch-example-parentage-v1"
    assert result.people_added == 2
    assert result.sources_added == 2
    assert result.files_added == 1
    assert result.assertions_added == 3
    assert result.relationships_added == 1
    assert connection.execute(
        """
        SELECT source_key.source_key, source.record_title
        FROM research_source_key AS source_key
        JOIN source ON source.source_id = source_key.source_id
        WHERE source_key.snapshot_id = ?
        ORDER BY source_key.source_key
        """,
        (result.snapshot_id,),
    ).fetchall() == [
        ("profile-child", "Example Child profile"),
        ("record-one", "Example workshop register"),
    ]
    assert connection.execute(
        "SELECT source_system FROM snapshot WHERE snapshot_id = ?",
        (result.snapshot_id,),
    ).fetchone() == ("research_batch",)
    assert connection.execute(
        """
        SELECT confidence
        FROM conclusion
        WHERE predicate = 'parent_child'
        """
    ).fetchone() == ("quarantined_contradiction",)
    question = connection.execute(
        """
        SELECT target_people_json, planned_searches, negative_results,
               current_conclusion
        FROM research_question
        WHERE title = 'Who were the example parents?'
        """
    ).fetchone()
    assert question is not None
    targets, planned, negative, current = map(json.loads, question)
    assert targets == [
        connection.execute(
            """
            SELECT person_id
            FROM person_identifier
            WHERE system = 'research_key'
              AND value = 'research:example-child'
            """
        ).fetchone()[0]
    ]
    assert [search["key"] for search in planned] == ["example-paid-search"]
    assert negative == []
    assert set(current) == {
        "summary",
        "line_anchor",
        "timeline",
        "associates",
        "hypotheses",
    }
    assert current["summary"] == "The example relationship remains unresolved."
    assert connection.execute(
        """
        SELECT raw_external_assertion_id, parsed_value
        FROM assertion
        WHERE predicate = 'event.birth'
        """
    ).fetchone() == (
        "example-child-birth",
        '{"end":null,"modifier":"about","start":{"day":null,"month":null,"year":1750}}',
    )
    assert connection.execute(
        """
        SELECT raw_external_relationship_id, raw_external_family_id,
               raw_external_child_link_id
        FROM relationship_assertion
        """
    ).fetchone() == (
        "research:example-parent-child",
        "research-family:example-child",
        "example-parent-child",
    )


def test_ingest_research_batch_persists_exact_input_and_source_paths(
    tmp_path: Path,
) -> None:
    record = _write_fixture_record(tmp_path)
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    batch = load_research_batch(batch_path)
    connection = create_store(tmp_path / "genealogy.sqlite")

    ingest_research_batch(
        connection,
        batch,
        tmp_path,
        batch_path=batch_path,
    )

    assert connection.execute(
        """
        SELECT snapshot_id, resolved_path, acquisition_root
        FROM research_batch_input
        """
    ).fetchall() == [
        (
            "research-batch-example-parentage-v1",
            str(batch_path.resolve()),
            str(tmp_path.resolve()),
        )
    ]
    assert connection.execute(
        """
        SELECT location.resolved_path, location.acquisition_root
        FROM source_file_location AS location
        JOIN source_file AS file
          ON file.source_file_id = location.source_file_id
        """
    ).fetchall() == [
        (
            str(record.resolve()),
            str(tmp_path.resolve()),
        )
    ]


def test_repeated_research_batch_idempotently_backfills_exact_paths(
    tmp_path: Path,
) -> None:
    record = _write_fixture_record(tmp_path)
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    batch = load_research_batch(batch_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(
        connection,
        batch,
        tmp_path,
        batch_path=batch_path,
    )
    connection.execute("DELETE FROM research_batch_input")
    connection.execute("DELETE FROM source_file_location")
    connection.execute("DROP TABLE research_source_key")
    connection.close()
    connection = create_store(tmp_path / "genealogy.sqlite")

    result = ingest_research_batch(
        connection,
        batch,
        tmp_path,
        batch_path=batch_path,
    )

    assert result.repeated is True
    assert connection.execute(
        "SELECT resolved_path FROM research_batch_input"
    ).fetchall() == [(str(batch_path.resolve()),)]
    assert connection.execute(
        "SELECT resolved_path FROM source_file_location"
    ).fetchall() == [(str(record.resolve()),)]
    assert connection.execute(
        """
        SELECT source_key.source_key, source.record_title
        FROM research_source_key AS source_key
        JOIN source ON source.source_id = source_key.source_id
        ORDER BY source_key.source_key
        """
    ).fetchall() == [
        ("profile-child", "Example Child profile"),
        ("record-one", "Example workshop register"),
    ]


def test_primary_name_conclusion_uses_supplied_review_metadata(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")

    ingest_research_batch(connection, batch, tmp_path)

    assert connection.execute(
        """
        SELECT conclusion.confidence, conclusion.rationale
        FROM conclusion
        JOIN assertion
          ON assertion.assertion_id = conclusion.chosen_assertion_id
        WHERE assertion.raw_external_assertion_id =
              'research-name:example-parent'
          AND conclusion.predicate = 'person.primary_name'
        """
    ).fetchone() == (
        "plausible_lead",
        "The workshop register supplies this example name.",
    )


def test_same_research_batch_is_a_no_op(tmp_path: Path) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    first = ingest_research_batch(connection, batch, tmp_path)

    repeated = ingest_research_batch(connection, batch, tmp_path)

    assert repeated.snapshot_id == first.snapshot_id
    assert repeated.repeated is True
    assert repeated.people_added == 0
    assert repeated.sources_added == 0
    assert repeated.files_added == 0
    assert repeated.assertions_added == 0
    assert repeated.relationships_added == 0
    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM source").fetchone()[0] == 2


def test_same_research_batch_id_with_different_digest_conflicts(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    changed = replace(
        batch,
        question=replace(batch.question, summary="A different current summary."),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, batch, tmp_path)

    with pytest.raises(SnapshotConflictError):
        ingest_research_batch(connection, changed, tmp_path)

    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 1
    assert connection.execute(
        "SELECT current_conclusion FROM research_question"
    ).fetchone()[0] == json.dumps(
        {
            "summary": batch.question.summary,
            "line_anchor": [
                {
                    "person_key": "example-child",
                    "person_id": connection.execute(
                        """
                        SELECT person_id FROM person_identifier
                        WHERE system = 'research_key'
                          AND value = 'research:example-child'
                        """
                    ).fetchone()[0],
                    "basis": "Example profile",
                    "confidence": "accepted_working",
                    "note": "Fixture line anchor.",
                }
            ],
            "timeline": [
                {
                    "date_text": "abt 1750",
                    "place_text": None,
                    "event_text": "Example Child was reportedly born.",
                    "source_keys": ["profile-child"],
                }
            ],
            "associates": [
                {
                    "name": "Example Registrar",
                    "relationship": "register signatory",
                    "source_keys": ["record-one"],
                    "note": "Fixture associate.",
                }
            ],
            "hypotheses": [
                {
                    "key": "example-h1",
                    "statement": "Example Parent was the father.",
                    "rank": 1,
                    "status": "unresolved",
                    "evidence": [
                        {
                            "source_key": "record-one",
                            "direction": "context",
                            "weight": "low",
                            "rationale": "The record supplies a lead only.",
                        }
                    ],
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def test_duplicate_source_file_hash_reuses_file_and_adds_source_link(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    first_batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, first_batch, tmp_path)
    original_file = connection.execute(
        """
        SELECT local_path, original_filename, rights_label
        FROM source_file
        """
    ).fetchone()
    second_file = replace(
        first_batch.sources[1].file,
        original_filename="renamed-copy.pdf",
        rights_label="restricted",
        ocr_status="raw",
        transcription_status="partial",
    )
    second_source = replace(first_batch.sources[1], file=second_file)
    second_batch = replace(
        first_batch,
        batch_id="example-parentage-v2",
        sources=(first_batch.sources[0], second_source),
    )

    result = ingest_research_batch(connection, second_batch, tmp_path)

    assert result.files_added == 0
    assert connection.execute("SELECT count(*) FROM source_file").fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM source_file_link"
    ).fetchone()[0] == 2
    assert connection.execute(
        """
        SELECT local_path, original_filename, rights_label
        FROM source_file
        """
    ).fetchone() == original_file
    assert connection.execute(
        """
        SELECT ocr_status, transcription_status
        FROM source_file
        """
    ).fetchone() == ("raw", "partial")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("rights_label", "unknown"),
        ("ocr_status", "finished"),
        ("transcription_status", "finished"),
    ),
)
def test_duplicate_source_file_rejects_invalid_metadata_before_writes(
    tmp_path: Path,
    field: str,
    invalid_value: str,
) -> None:
    """A reused hash must not bypass controlled source-file metadata."""
    _write_fixture_record(tmp_path)
    first_batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, first_batch, tmp_path)
    invalid_file = replace(
        first_batch.sources[1].file,
        **{field: invalid_value},
    )
    second_batch = replace(
        first_batch,
        batch_id="example-parentage-v2",
        sources=(
            first_batch.sources[0],
            replace(first_batch.sources[1], file=invalid_file),
        ),
    )

    with pytest.raises(
        ResearchBatchValidationError,
        match=rf"{field}.*invalid",
    ):
        ingest_research_batch(connection, second_batch, tmp_path)

    assert connection.execute(
        "SELECT count(*) FROM snapshot WHERE source_system = 'research_batch'"
    ).fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM source").fetchone()[0] == 2
    assert connection.execute(
        "SELECT count(*) FROM source_file_link"
    ).fetchone()[0] == 1


def test_duplicate_restricted_file_cannot_register_public_path(
    tmp_path: Path,
) -> None:
    """Hash reuse must retain the stored rights boundary for every new location."""
    private_record = _write_fixture_record(tmp_path)
    first_batch = _load_fixture_batch(tmp_path)
    restricted_file = replace(
        first_batch.sources[1].file,
        rights_label="restricted",
    )
    first_batch = replace(
        first_batch,
        sources=(
            first_batch.sources[0],
            replace(first_batch.sources[1], file=restricted_file),
        ),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, first_batch, tmp_path)
    public_record = tmp_path / "sources" / "same-estate.pdf"
    public_record.parent.mkdir()
    public_record.write_bytes(private_record.read_bytes())
    public_file = replace(
        restricted_file,
        path="sources/same-estate.pdf",
        rights_label="public_domain",
    )
    second_batch = replace(
        first_batch,
        batch_id="example-parentage-v2",
        sources=(
            first_batch.sources[0],
            replace(first_batch.sources[1], file=public_file),
        ),
    )

    with pytest.raises(ValueError, match=r"below data/private"):
        ingest_research_batch(connection, second_batch, tmp_path)

    assert connection.execute(
        "SELECT count(*) FROM snapshot WHERE source_system = 'research_batch'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM source_file_location"
    ).fetchone()[0] == 1


def test_later_batch_selects_current_claim_without_deleting_competing_provenance(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    first_batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, first_batch, tmp_path)
    alternate_parent = replace(
        first_batch.people[1],
        key="alternate-parent",
        display_name="Alternate Parent",
        familysearch_id="CCCC-333",
    )
    changed_assertion = replace(
        first_batch.assertions[0],
        confidence="plausible_lead",
        rationale="The later batch curates this claim as a lead.",
    )
    changed_relationship = replace(
        first_batch.relationships[0],
        key="alternate-parent-child",
        parent_key="alternate-parent",
        confidence="accepted_working",
        rationale="The later batch curates the alternate parent.",
    )
    second_batch = replace(
        first_batch,
        batch_id="example-parentage-v2",
        people=(first_batch.people[0], alternate_parent),
        assertions=(changed_assertion,),
        relationships=(changed_relationship,),
    )

    ingest_research_batch(connection, second_batch, tmp_path)

    assert connection.execute(
        """
        SELECT count(*) FROM assertion
        WHERE predicate = 'event.birth'
        """
    ).fetchone()[0] == 2
    assert connection.execute(
        """
        SELECT a.snapshot_id, c.confidence
        FROM conclusion AS c
        JOIN assertion AS a ON a.assertion_id = c.chosen_assertion_id
        WHERE c.subject_type = 'person' AND c.predicate = 'event.birth'
        """
    ).fetchone() == (
        "research-batch-example-parentage-v2",
        "plausible_lead",
    )
    assert connection.execute(
        "SELECT count(*) FROM relationship_assertion"
    ).fetchone()[0] == 2
    relationship_conclusions = connection.execute(
        """
        SELECT parent.value, child.value, c.confidence
        FROM conclusion AS c
        JOIN relationship_assertion AS relationship
          ON relationship.relationship_assertion_id =
             c.chosen_relationship_assertion_id
        JOIN person_identifier AS parent
          ON parent.person_id = relationship.subject_person_id
         AND parent.system = 'research_key'
        JOIN person_identifier AS child
          ON child.person_id = relationship.object_person_id
         AND child.system = 'research_key'
        WHERE c.subject_type = 'relationship'
          AND c.predicate = 'parent_child'
        """
    ).fetchall()
    assert relationship_conclusions == [
        (
            "research:alternate-parent",
            "research:example-child",
            "accepted_working",
        )
    ]
    assert connection.execute("SELECT count(*) FROM source").fetchone()[0] == 4


def test_research_parent_choice_retires_tree_current_for_same_child_and_role(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    tree_snapshot = extract_snapshot(
        build_rm_fixture(tmp_path / "tree.rmtree"),
        "tree-001",
    )
    ingest_snapshot(connection, tree_snapshot, "tree-hash")
    batch = _load_fixture_batch(tmp_path)
    research_child = replace(
        batch.people[0],
        familysearch_id="CCCC-333",
    )
    research_parent = replace(
        batch.people[1],
        familysearch_id=None,
    )
    research_relationship = replace(
        batch.relationships[0],
        confidence="accepted_working",
        rationale="The research batch selects the replacement father.",
    )
    replacement_batch = replace(
        batch,
        people=(research_child, research_parent),
        relationships=(research_relationship,),
    )

    ingest_research_batch(connection, replacement_batch, tmp_path)

    child_id = connection.execute(
        """
        SELECT person_id
        FROM person_identifier
        WHERE system = 'familysearch' AND value = 'CCCC-333'
        """
    ).fetchone()[0]
    current_fathers = connection.execute(
        """
        SELECT relationship.snapshot_id,
               relationship.raw_external_relationship_id
        FROM conclusion AS current
        JOIN relationship_assertion AS relationship
          ON relationship.relationship_assertion_id =
             current.chosen_relationship_assertion_id
        WHERE relationship.predicate = 'parent_child'
          AND relationship.object_person_id = ?
          AND relationship.role = 'father'
        """,
        (child_id,),
    ).fetchall()
    assert current_fathers == [
        (
            "research-batch-example-parentage-v1",
            "research:example-parent-child",
        )
    ]
    assert connection.execute(
        """
        SELECT raw_external_relationship_id
        FROM relationship_assertion
        WHERE predicate = 'parent_child'
          AND object_person_id = ?
          AND role = 'father'
        ORDER BY raw_external_relationship_id
        """,
        (child_id,),
    ).fetchall() == [
        ("child_link:1",),
        ("research:example-parent-child",),
    ]


def test_source_file_processing_status_never_moves_backward_or_from_terminal(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    terminal_file = replace(
        batch.sources[1].file,
        ocr_status="not_applicable",
        transcription_status="not_applicable",
    )
    terminal_batch = replace(
        batch,
        sources=(batch.sources[0], replace(batch.sources[1], file=terminal_file)),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, terminal_batch, tmp_path)
    regressive_file = replace(
        batch.sources[1].file,
        ocr_status="corrected",
        transcription_status="complete",
    )
    regressive_batch = replace(
        batch,
        batch_id="example-parentage-v2",
        sources=(batch.sources[0], replace(batch.sources[1], file=regressive_file)),
    )

    ingest_research_batch(connection, regressive_batch, tmp_path)

    assert connection.execute(
        "SELECT ocr_status, transcription_status FROM source_file"
    ).fetchone() == ("not_applicable", "not_applicable")


def test_file_change_after_preflight_rolls_back_complete_batch(
    tmp_path: Path,
) -> None:
    record = _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")

    def change_file() -> int:
        record.write_bytes(b"changed after preflight")
        return 0

    connection.create_function("change_file", 0, change_file)
    connection.execute(
        """
        CREATE TEMP TRIGGER change_file_during_ingest
        AFTER INSERT ON source_file
        BEGIN
            SELECT change_file();
        END
        """
    )

    with pytest.raises(ValueError, match="changed"):
        ingest_research_batch(
            connection,
            batch,
            tmp_path,
            batch_path=tmp_path / "batch.json",
        )

    for table in (
        "snapshot",
        "research_batch_input",
        "person",
        "person_identifier",
        "source",
        "source_file",
        "source_file_location",
        "source_file_link",
        "assertion",
        "relationship_assertion",
        "conclusion",
        "research_question",
    ):
        assert connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] == 0


def test_dangling_canonical_identity_rolls_back_sources_and_question(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES ('corrupt-seed', 'corrupt-seed', 'test', 0, 0, 0, 0, 0)
        """
    )
    connection.execute(
        """
        INSERT INTO person_identifier(
            person_id, system, value, scope_snapshot_id,
            first_seen_snapshot_id, last_seen_snapshot_id
        ) VALUES (
            'missing-person', 'research_key', 'research:example-child', NULL,
            'corrupt-seed', 'corrupt-seed'
        )
        """
    )
    connection.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(ValueError, match="missing canonical person"):
        ingest_research_batch(connection, batch, tmp_path)

    assert connection.execute(
        "SELECT count(*) FROM snapshot WHERE source_system = 'research_batch'"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM source").fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM research_question"
    ).fetchone()[0] == 0


def test_familysearch_and_research_key_disagreement_rolls_back(
    tmp_path: Path,
) -> None:
    _write_fixture_record(tmp_path)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")
    _add_exact_identity(
        connection,
        snapshot_id="seed-familysearch",
        system="familysearch",
        value="AAAA-111",
    )
    _add_exact_identity(
        connection,
        snapshot_id="seed-research-key",
        system="research_key",
        value="research:example-child",
    )

    with pytest.raises(
        ValueError,
        match="Identifiers resolve to different canonical people",
    ):
        ingest_research_batch(connection, batch, tmp_path)

    assert connection.execute(
        "SELECT count(*) FROM snapshot WHERE source_system = 'research_batch'"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM source").fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM research_question"
    ).fetchone()[0] == 0


def test_research_batch_rejects_source_file_outside_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    outside.write_bytes(b"outside")
    symlink = (
        tmp_path
        / "data"
        / "private"
        / "research"
        / "example-workshop.pdf"
    )
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(outside)
    batch = _load_fixture_batch(tmp_path)
    connection = create_store(tmp_path / "genealogy.sqlite")

    with pytest.raises(ValueError, match="below project root"):
        ingest_research_batch(connection, batch, tmp_path)

    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 0


@pytest.mark.parametrize(
    "rights_label",
    ("personal_research", "restricted", "private_family"),
)
def test_non_public_source_file_must_resolve_below_data_private(
    tmp_path: Path,
    rights_label: str,
) -> None:
    """Non-public originals outside data/private would cross the rights boundary."""
    outside_private = tmp_path / "records" / "example-workshop.pdf"
    outside_private.parent.mkdir()
    outside_private.write_bytes(b"example estate bytes")
    batch = _load_fixture_batch(tmp_path)
    file = replace(
        batch.sources[1].file,
        path="records/example-workshop.pdf",
        rights_label=rights_label,
    )
    batch = replace(
        batch,
        sources=(
            batch.sources[0],
            replace(batch.sources[1], file=file),
        ),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")

    with pytest.raises(ValueError, match=r"below data/private"):
        ingest_research_batch(connection, batch, tmp_path)

    assert connection.execute("SELECT count(*) FROM snapshot").fetchone()[0] == 0


def test_public_domain_source_file_may_resolve_outside_data_private(
    tmp_path: Path,
) -> None:
    """Rights-cleared originals may live in a tracked project source directory."""
    public_record = tmp_path / "sources" / "example-workshop.pdf"
    public_record.parent.mkdir()
    public_record.write_bytes(b"example estate bytes")
    batch = _load_fixture_batch(tmp_path)
    file = replace(
        batch.sources[1].file,
        path="sources/example-workshop.pdf",
        rights_label="public_domain",
    )
    batch = replace(
        batch,
        sources=(
            batch.sources[0],
            replace(batch.sources[1], file=file),
        ),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")

    result = ingest_research_batch(connection, batch, tmp_path)

    assert result.files_added == 1
    assert connection.execute(
        "SELECT local_path, rights_label FROM source_file"
    ).fetchone() == ("sources/example-workshop.pdf", "public_domain")


def test_repeated_legacy_batch_still_enforces_non_public_path_boundary(
    tmp_path: Path,
) -> None:
    """An old snapshot identity must not bypass today's private-path preflight."""
    legacy_record = tmp_path / "records" / "example-workshop.pdf"
    legacy_record.parent.mkdir()
    legacy_record.write_bytes(b"example estate bytes")
    batch = _load_fixture_batch(tmp_path)
    file = replace(
        batch.sources[1].file,
        path="records/example-workshop.pdf",
    )
    batch = replace(
        batch,
        sources=(
            batch.sources[0],
            replace(batch.sources[1], file=file),
        ),
    )
    connection = create_store(tmp_path / "genealogy.sqlite")
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system, import_scope,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES (?, ?, 'research_batch', ?, 0, 0, 0, 0, 0)
        """,
        (
            f"research-batch-{batch.batch_id}",
            batch.digest(),
            batch.question.title,
        ),
    )

    with pytest.raises(ValueError, match=r"below data/private"):
        ingest_research_batch(connection, batch, tmp_path)
