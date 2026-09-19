"""End-to-end command-line pipeline and safety-boundary tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import genealogy.cli as cli
from genealogy.cli import main
from genealogy.rm_reader import extract_snapshot
from genealogy.snapshots import sha256_file
from tests.fixtures.research_batch import (
    valid_research_payload,
    write_research_batch_fixture,
)
from tests.fixtures.rm_fixture import build_rm_fixture


def _write_bridge_seed(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "people": [
                    {
                        "seed_id": "imported-anchor",
                        "display_name": "Private imported anchor",
                        "living": False,
                        "familysearch_id": "AAAA-111",
                    },
                    {
                        "seed_id": "private-root",
                        "display_name": "Private root",
                        "living": True,
                        "familysearch_id": None,
                    },
                ],
                "relationships": [
                    {"parent": "imported-anchor", "child": "private-root"}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _private_root_id(database: Path) -> str:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            """
            SELECT person_id
            FROM person_identifier
            WHERE system = 'private_seed' AND value = 'private-root'
            """
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def _snapshot_count(database: Path) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(
            connection.execute("SELECT count(*) FROM snapshot").fetchone()[0]
        )
    finally:
        connection.close()


def test_cli_runs_manifest_ingestion_cohorts_and_coverage_without_source_writes(
    tmp_path: Path,
) -> None:
    """Breaking any pipeline command or mutating the source must fail this test."""
    rm_path = build_rm_fixture(tmp_path / "fixture.rmtree")
    seed_path = _write_bridge_seed(tmp_path / "private-seed.json")
    database = tmp_path / "genealogy.sqlite"
    manifest_path = tmp_path / "manifest.json"
    markdown = tmp_path / "coverage.md"
    json_output = tmp_path / "coverage.json"
    source_hash_before = sha256_file(rm_path)

    assert main(
        [
            "manifest",
            "--root",
            str(tmp_path),
            "--output",
            str(manifest_path),
            str(rm_path),
        ]
    ) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"] == [
        {
            "path": "fixture.rmtree",
            "sha256": source_hash_before,
            "size": rm_path.stat().st_size,
        }
    ]
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "fixture-001",
            "--manifest-hash",
            source_hash_before,
            str(rm_path),
        ]
    ) == 0
    assert main(
        ["ingest-seed", "--database", str(database), str(seed_path)]
    ) == 0
    assert main(
        [
            "cohorts",
            "--database",
            str(database),
            "--root-person-id",
            _private_root_id(database),
        ]
    ) == 0
    assert main(
        [
            "coverage",
            "--database",
            str(database),
            "--cohort",
            "Z",
            "--markdown",
            str(markdown),
            "--json",
            str(json_output),
        ]
    ) == 0

    report = json.loads(json_output.read_text(encoding="utf-8"))
    assert report["summary"]["eligible_people"] == 3
    assert next(
        metric for metric in report["metrics"] if metric["name"] == "people"
    ) == {
        "cohort": "Z",
        "eligible": 3,
        "evidence_floor": "accepted_working",
        "included": 3,
        "name": "people",
        "unit": "people",
        "unknown": 0,
    }
    assert "- Eligible people: 3" in markdown.read_text(encoding="utf-8")
    assert sha256_file(rm_path) == source_hash_before


def test_manifest_validates_every_input_before_replacing_output(
    tmp_path: Path, capsys
) -> None:
    """Opening inputs one by one could overwrite a valid manifest on late failure."""
    valid = tmp_path / "valid.rmtree"
    valid.write_bytes(b"valid")
    missing = tmp_path / "missing.rmtree"
    output = tmp_path / "manifest.json"
    output.write_text("keep-me\n", encoding="utf-8")

    result = main(
        [
            "manifest",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            str(valid),
            str(missing),
        ]
    )

    assert result != 0
    assert output.read_text(encoding="utf-8") == "keep-me\n"
    assert capsys.readouterr().err.splitlines() == [
        f"error: input file does not exist: {missing}"
    ]


def test_manifest_rejects_hard_link_output_before_writing_source(
    tmp_path: Path, capsys
) -> None:
    """Comparing only path strings lets an output hard link overwrite the input."""
    rm_path = tmp_path / "fixture.rmtree"
    original_bytes = b"immutable RootsMagic bytes"
    rm_path.write_bytes(original_bytes)
    original_hash = sha256_file(rm_path)
    output = tmp_path / "manifest.json"
    os.link(rm_path, output)

    result = main(
        [
            "manifest",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            str(rm_path),
        ]
    )

    assert result != 0
    assert rm_path.read_bytes() == original_bytes
    assert sha256_file(rm_path) == original_hash
    assert capsys.readouterr().err.splitlines() == [
        f"error: manifest output cannot replace input file: {rm_path}"
    ]


def test_ingest_rm_rejects_missing_input_before_creating_database(
    tmp_path: Path, capsys
) -> None:
    """Creating a store before validating the snapshot leaves misleading state."""
    database = tmp_path / "genealogy.sqlite"
    missing = tmp_path / "missing.rmtree"

    result = main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "missing-001",
            "--manifest-hash",
            "abc123",
            str(missing),
        ]
    )

    assert result != 0
    assert not database.exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: input file does not exist: {missing}"
    ]


def test_ingest_rm_rejects_hard_link_database_before_writing_source(
    tmp_path: Path, capsys
) -> None:
    """Opening a hard-linked database path must not modify the RootsMagic inode."""
    rm_path = build_rm_fixture(tmp_path / "fixture.rmtree")
    source_bytes = rm_path.read_bytes()
    source_hash = sha256_file(rm_path)
    database = tmp_path / "genealogy.sqlite"
    os.link(rm_path, database)

    result = main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "fixture-001",
            "--manifest-hash",
            source_hash,
            str(rm_path),
        ]
    )

    assert result != 0
    assert rm_path.read_bytes() == source_bytes
    assert sha256_file(rm_path) == source_hash
    assert capsys.readouterr().err.splitlines() == [
        "error: RootsMagic input and canonical database must be different"
    ]


def test_ingest_rm_rejects_malformed_manifest_hash_before_extraction(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """A non-SHA-256 value must fail before extraction or database mutation."""
    rm_path = build_rm_fixture(tmp_path / "fixture.rmtree")
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0

    extracted = False

    def observed_extraction(path: Path, snapshot_id: str):
        nonlocal extracted
        extracted = True
        return extract_snapshot(path, snapshot_id)

    monkeypatch.setattr(cli, "extract_snapshot", observed_extraction)

    result = main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "fixture-001",
            "--manifest-hash",
            "abc123",
            str(rm_path),
        ]
    )

    assert result != 0
    assert extracted is False
    assert _snapshot_count(database) == 0
    assert capsys.readouterr().err.splitlines() == [
        "error: manifest hash must be a 64-character hexadecimal SHA-256 digest: abc123"
    ]


def test_ingest_rm_rejects_well_formed_wrong_manifest_hash(
    tmp_path: Path, capsys
) -> None:
    """A valid-looking digest for different bytes must not authorize ingestion."""
    rm_path = build_rm_fixture(tmp_path / "fixture.rmtree")
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    wrong_hash = "0" * 64
    actual_hash = sha256_file(rm_path)

    result = main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "fixture-001",
            "--manifest-hash",
            wrong_hash,
            str(rm_path),
        ]
    )

    assert result != 0
    assert _snapshot_count(database) == 0
    assert capsys.readouterr().err.splitlines() == [
        "error: manifest hash does not match RootsMagic input "
        f"{rm_path}: expected {wrong_hash}, got {actual_hash}"
    ]


def test_ingest_rm_rejects_source_change_during_extraction(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Changing bytes after the first hash must fail before canonical writes."""
    rm_path = build_rm_fixture(tmp_path / "fixture.rmtree")
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    expected_hash = sha256_file(rm_path)

    def mutating_extraction(path: Path, snapshot_id: str):
        snapshot = extract_snapshot(path, snapshot_id)
        with path.open("ab") as handle:
            handle.write(b"changed during extraction")
        return snapshot

    monkeypatch.setattr(cli, "extract_snapshot", mutating_extraction)

    result = main(
        [
            "ingest-rm",
            "--database",
            str(database),
            "--snapshot-id",
            "fixture-001",
            "--manifest-hash",
            expected_hash,
            str(rm_path),
        ]
    )

    assert result != 0
    assert _snapshot_count(database) == 0
    assert capsys.readouterr().err.splitlines() == [
        f"error: RootsMagic input changed during extraction: {rm_path}"
    ]


def test_coverage_rejects_same_output_paths_before_opening_database(
    tmp_path: Path, capsys
) -> None:
    """Two report formats at one path would silently replace one another."""
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    shared_output = tmp_path / "coverage.out"

    result = main(
        [
            "coverage",
            "--database",
            str(database),
            "--cohort",
            "Z",
            "--markdown",
            str(shared_output),
            "--json",
            str(shared_output),
        ]
    )

    assert result != 0
    assert not shared_output.exists()
    assert capsys.readouterr().err.splitlines() == [
        "error: Markdown and JSON outputs must be different paths"
    ]


def test_parser_error_is_one_actionable_stderr_line(capsys) -> None:
    """Default argparse usage output would violate the concise error contract."""
    result = main(["coverage", "--cohort", "Q"])

    assert result != 0
    assert capsys.readouterr().err.splitlines() == [
        "error: coverage requires --database"
    ]


def test_domain_error_is_one_actionable_stderr_line(
    tmp_path: Path, capsys
) -> None:
    """Leaking a ValueError traceback would break the user-error contract."""
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    unknown_root = "00000000-0000-0000-0000-000000000001"

    result = main(
        [
            "cohorts",
            "--database",
            str(database),
            "--root-person-id",
            unknown_root,
        ]
    )

    assert result != 0
    assert capsys.readouterr().err.splitlines() == [
        f"error: unknown root person {unknown_root}"
    ]


def _write_research_source(
    root: Path,
    relative_path: str = "data/private/research/example-workshop.pdf",
) -> Path:
    source = root / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"fictional CLI estate record")
    return source


def _write_research_payload(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_cli_ingests_repeats_and_renders_research_without_source_writes(
    tmp_path: Path,
    capsys,
) -> None:
    """The private workflow must be complete, repeatable, and source preserving."""
    source = _write_research_source(tmp_path)
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    database = tmp_path / "genealogy.sqlite"
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    batch_hash_before = sha256_file(batch_path)
    source_hash_before = sha256_file(source)
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0
    assert main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0
    assert {path.name for path in output_dir.iterdir()} == {
        "direct-line-audit.md",
        "person-dossier.md",
        "hypothesis-matrix.md",
        "action-queue.md",
        "research-state.json",
    }
    capsys.readouterr()

    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0

    assert "repeated batch" in capsys.readouterr().out
    assert sha256_file(batch_path) == batch_hash_before
    assert sha256_file(source) == source_hash_before


def test_ingest_research_reports_missing_database_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    """Creating a missing canonical database would conceal a path mistake."""
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    missing = tmp_path / "missing.sqlite"

    result = main(
        [
            "ingest-research",
            "--database",
            str(missing),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    )

    assert result != 0
    assert not missing.exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: database does not exist: {missing}"
    ]


def test_ingest_research_reports_missing_root_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    """An incorrect project root must fail before the batch is read."""
    database = tmp_path / "genealogy.sqlite"
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    missing = tmp_path / "missing-root"
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    result = main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(missing),
            str(batch_path),
        ]
    )

    assert result != 0
    assert capsys.readouterr().err.splitlines() == [
        f"error: research root does not exist: {missing}"
    ]


def test_ingest_research_reports_missing_input_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    """A missing batch must not produce a traceback or partial ingestion."""
    database = tmp_path / "genealogy.sqlite"
    missing = tmp_path / "missing.json"
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    result = main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(missing),
        ]
    )

    assert result != 0
    assert capsys.readouterr().err.splitlines() == [
        f"error: research batch does not exist: {missing}"
    ]


def test_ingest_research_rejects_source_resolving_outside_root(
    tmp_path: Path,
    capsys,
) -> None:
    """A symlink must not bypass the private source-root boundary."""
    root = tmp_path / "root"
    root.mkdir()
    records = root / "data" / "private" / "research"
    records.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside root")
    (records / "example-workshop.pdf").symlink_to(outside)
    batch_path = write_research_batch_fixture(root / "batch.json")
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    result = main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(root),
            str(batch_path),
        ]
    )

    assert result != 0
    assert _snapshot_count(database) == 0
    assert capsys.readouterr().err.splitlines() == [
        "error: source record-one file must stay below project root"
    ]


def test_research_report_reports_missing_output_directory_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    """Reports must not invent a destination after a path typo."""
    database = tmp_path / "genealogy.sqlite"
    missing = tmp_path / "missing-output"
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(missing),
        ]
    )

    assert result != 0
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output directory does not exist: {missing}"
    ]


def test_research_report_reports_unknown_question_title_on_one_line(
    tmp_path: Path,
    capsys,
) -> None:
    """An exact-title miss must not silently choose another investigation."""
    database = tmp_path / "genealogy.sqlite"
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    assert main(["init-store", "--database", str(database)]) == 0
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Unknown question",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result != 0
    assert not tuple(output_dir.iterdir())
    assert capsys.readouterr().err.splitlines() == [
        "error: research question not found: Unknown question"
    ]


def test_research_report_rejects_database_output_collision_before_writes(
    tmp_path: Path,
    capsys,
) -> None:
    """A report filename matching the database must not corrupt canonical state."""
    source = _write_research_source(tmp_path)
    batch_path = write_research_batch_fixture(tmp_path / "batch.json")
    database = tmp_path / "research-state.json"
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0
    database_hash = sha256_file(database)
    source_hash = sha256_file(source)
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result != 0
    assert sha256_file(database) == database_hash
    assert sha256_file(source) == source_hash
    assert not (tmp_path / "direct-line-audit.md").exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output cannot replace database: {database}"
    ]


def test_research_report_rejects_batch_input_collision_before_writes(
    tmp_path: Path,
    capsys,
) -> None:
    """A prior batch must remain immutable when its name matches a report."""
    _write_research_source(tmp_path)
    batch_path = write_research_batch_fixture(tmp_path / "research-state.json")
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0
    batch_hash = sha256_file(batch_path)
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result != 0
    assert sha256_file(batch_path) == batch_hash
    assert not (tmp_path / "direct-line-audit.md").exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output cannot replace research batch input: {batch_path}"
    ]


def test_research_report_rejects_registered_source_collision_before_writes(
    tmp_path: Path,
    capsys,
) -> None:
    """A registered source must never be overwritten by a generated report."""
    source = _write_research_source(tmp_path, "action-queue.md")
    payload = valid_research_payload()
    sources = payload["sources"]
    assert isinstance(sources, list)
    file_metadata = sources[1]["file"]
    assert isinstance(file_metadata, dict)
    file_metadata["path"] = "action-queue.md"
    file_metadata["original_filename"] = "action-queue.md"
    file_metadata["rights_label"] = "public_domain"
    batch_path = _write_research_payload(tmp_path / "batch.json", payload)
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0
    source_hash = sha256_file(source)
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result != 0
    assert sha256_file(source) == source_hash
    assert not (tmp_path / "direct-line-audit.md").exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output cannot replace registered source file: {source}"
    ]


def test_research_report_protects_changed_batch_at_registered_original_path(
    tmp_path: Path,
    capsys,
) -> None:
    """Content-based detection lets a changed batch be overwritten at its known path."""
    _write_research_source(tmp_path)
    payload = valid_research_payload()
    batch_path = _write_research_payload(
        tmp_path / "research-state.json",
        payload,
    )
    database = tmp_path / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(tmp_path),
            str(batch_path),
        ]
    ) == 0
    question = payload["question"]
    assert isinstance(question, dict)
    question["summary"] = "Changed after ingestion and reformatted."
    batch_path.write_text(
        json.dumps(payload, indent=4, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    changed_hash = sha256_file(batch_path)
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert result != 0
    assert sha256_file(batch_path) == changed_hash
    assert not (tmp_path / "direct-line-audit.md").exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output cannot replace research batch input: {batch_path}"
    ]


def test_research_report_protects_changed_source_at_registered_original_path(
    tmp_path: Path,
    capsys,
) -> None:
    """Root guessing and old hashes must not lose a source's original path."""
    root = tmp_path / "acquisition-root"
    root.mkdir()
    source = _write_research_source(root, "action-queue.md")
    payload = valid_research_payload()
    sources = payload["sources"]
    assert isinstance(sources, list)
    file_metadata = sources[1]["file"]
    assert isinstance(file_metadata, dict)
    file_metadata["path"] = "action-queue.md"
    file_metadata["original_filename"] = "action-queue.md"
    file_metadata["rights_label"] = "public_domain"
    batch_path = _write_research_payload(root / "batch.json", payload)
    database_dir = tmp_path / "store"
    database_dir.mkdir()
    database = database_dir / "genealogy.sqlite"
    assert main(["init-store", "--database", str(database)]) == 0
    assert main(
        [
            "ingest-research",
            "--database",
            str(database),
            "--root",
            str(root),
            str(batch_path),
        ]
    ) == 0
    source.write_bytes(b"changed registered source")
    changed_hash = sha256_file(source)
    capsys.readouterr()

    result = main(
        [
            "research-report",
            "--database",
            str(database),
            "--question-title",
            "Who were the example parents?",
            "--output-dir",
            str(root),
        ]
    )

    assert result != 0
    assert sha256_file(source) == changed_hash
    assert not (root / "direct-line-audit.md").exists()
    assert capsys.readouterr().err.splitlines() == [
        f"error: research report output cannot replace registered source file: {source}"
    ]
