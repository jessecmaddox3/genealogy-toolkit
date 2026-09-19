"""Command-line orchestration for the local genealogy data pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from genealogy.cohorts import COHORT_CODES, recompute_cohorts
from genealogy.coverage import build_coverage_report
from genealogy.render import render_coverage_json, render_coverage_markdown
from genealogy.research_records import load_research_batch
from genealogy.research_render import load_research_state, render_research_outputs
from genealogy.research_store import ingest_research_batch
from genealogy.rm_reader import (
    RootsMagicExtractionError,
    RootsMagicSchemaError,
    extract_snapshot,
)
from genealogy.seeds import (
    SeedValidationError,
    ingest_private_seed,
    load_private_seed,
)
from genealogy.snapshots import build_manifest, sha256_file, write_manifest
from genealogy.store import (
    SnapshotConflictError,
    create_store,
    ingest_snapshot,
)


class CliError(ValueError):
    """A user-correctable command-line error."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="genealogy")
    commands = parser.add_subparsers(dest="command")

    manifest = commands.add_parser("manifest")
    manifest.add_argument("--root")
    manifest.add_argument("--output")
    manifest.add_argument("inputs", nargs="*")

    init_store = commands.add_parser("init-store")
    init_store.add_argument("--database")

    ingest_rm = commands.add_parser("ingest-rm")
    ingest_rm.add_argument("--database")
    ingest_rm.add_argument("--snapshot-id")
    ingest_rm.add_argument("--manifest-hash")
    ingest_rm.add_argument("input", nargs="?")

    ingest_seed = commands.add_parser("ingest-seed")
    ingest_seed.add_argument("--database")
    ingest_seed.add_argument("input", nargs="?")

    cohorts = commands.add_parser("cohorts")
    cohorts.add_argument("--database")
    cohorts.add_argument("--root-person-id")

    coverage = commands.add_parser("coverage")
    coverage.add_argument("--database")
    coverage.add_argument("--cohort")
    coverage.add_argument("--markdown")
    coverage.add_argument("--json")

    ingest_research = commands.add_parser("ingest-research")
    ingest_research.add_argument("--database")
    ingest_research.add_argument("--root")
    ingest_research.add_argument("input", nargs="?")

    research_report = commands.add_parser("research-report")
    research_report.add_argument("--database")
    research_report.add_argument("--question-title")
    research_report.add_argument("--output-dir")

    research_report.add_argument("--html", action="store_true", help="Also write a standalone HTML reader")

    demo = commands.add_parser("demo", help="Create the entirely invented offline example")
    demo.add_argument("--output", required=True)

    return parser


def _required(value: str | None, command: str, option: str) -> str:
    if value is None or not value.strip():
        raise CliError(f"{command} requires {option}")
    return value


def _existing_directory(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise CliError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise CliError(f"{label} is not a directory: {path}")
    return path


def _existing_file(value: str, label: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise CliError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise CliError(f"{label} is not a file: {path}")
    return path


def _output_file(value: str, label: str) -> Path:
    path = Path(value)
    if path.exists() and not path.is_file():
        raise CliError(f"{label} is not a file: {path}")
    parent = path.parent
    if not parent.exists():
        raise CliError(f"{label} directory does not exist: {parent}")
    if not parent.is_dir():
        raise CliError(f"{label} directory is not a directory: {parent}")
    return path


def _same_path(left: Path, right: Path) -> bool:
    try:
        if left.exists() and right.exists():
            return left.samefile(right)
    except OSError:
        pass
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _close_after(
    database: Path, operation: Callable[[sqlite3.Connection], object]
) -> object:
    connection = create_store(database)
    try:
        return operation(connection)
    finally:
        connection.close()


def _manifest(args: argparse.Namespace) -> None:
    root = _existing_directory(
        _required(args.root, "manifest", "--root"),
        "manifest root",
    )
    output = _output_file(
        _required(args.output, "manifest", "--output"),
        "manifest output",
    )
    if not args.inputs:
        raise CliError("manifest requires at least one input file")
    inputs = tuple(_existing_file(value, "input file") for value in args.inputs)
    resolved_root = root.resolve()
    for input_path in inputs:
        try:
            input_path.resolve().relative_to(resolved_root)
        except ValueError as error:
            raise CliError(
                f"input file is outside manifest root: {input_path}"
            ) from error
        if _same_path(input_path, output):
            raise CliError(f"manifest output cannot replace input file: {input_path}")

    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            previous = None
        if not isinstance(previous, dict) or previous.get("manifest_version") != 1 or not isinstance(previous.get("files"), list):
            raise CliError("manifest output already exists and is not an acquisition manifest; choose a new output path")
    write_manifest(build_manifest(inputs, root), output)
    noun = "file" if len(inputs) == 1 else "files"
    print(f"Wrote manifest for {len(inputs)} {noun}: {output}")


def _init_store(args: argparse.Namespace) -> None:
    database = _output_file(
        _required(args.database, "init-store", "--database"),
        "database",
    )
    connection = create_store(database)
    connection.close()
    print(f"Initialized canonical store: {database}")


def _ingest_rm(args: argparse.Namespace) -> None:
    input_path = _existing_file(
        _required(args.input, "ingest-rm", "INPUT"),
        "input file",
    )
    if input_path.suffix.casefold() != ".rmtree":
        raise CliError(f"RootsMagic input must end in .rmtree: {input_path}")
    database_value = _required(args.database, "ingest-rm", "--database")
    database = _existing_file(database_value, "database")
    if _same_path(input_path, database):
        raise CliError("RootsMagic input and canonical database must be different")
    snapshot_id = _required(args.snapshot_id, "ingest-rm", "--snapshot-id")
    manifest_hash = _required(
        args.manifest_hash, "ingest-rm", "--manifest-hash"
    )
    if re.fullmatch(r"[0-9a-fA-F]{64}", manifest_hash) is None:
        raise CliError(
            "manifest hash must be a 64-character hexadecimal SHA-256 "
            f"digest: {manifest_hash}"
        )
    manifest_hash = manifest_hash.casefold()
    source_hash_before = sha256_file(input_path)
    if source_hash_before != manifest_hash:
        raise CliError(
            f"manifest hash does not match RootsMagic input {input_path}: "
            f"expected {manifest_hash}, got {source_hash_before}"
        )

    snapshot = extract_snapshot(input_path, snapshot_id)
    source_hash_after = sha256_file(input_path)
    if source_hash_after != source_hash_before:
        raise CliError(
            f"RootsMagic input changed during extraction: {input_path}"
        )
    result = _close_after(
        database,
        lambda connection: ingest_snapshot(
            connection, snapshot, manifest_hash
        ),
    )
    print(
        f"Ingested RootsMagic snapshot {snapshot_id}: "
        f"{len(snapshot.people)} people, {len(snapshot.events)} events, "
        f"{result.assertions_added} assertions, "
        f"{result.relationships_added} relationships"
    )


def _ingest_seed(args: argparse.Namespace) -> None:
    input_path = _existing_file(
        _required(args.input, "ingest-seed", "INPUT"),
        "input file",
    )
    database = _existing_file(
        _required(args.database, "ingest-seed", "--database"),
        "database",
    )
    if _same_path(input_path, database):
        raise CliError("private seed and canonical database must be different")

    seed = load_private_seed(input_path)
    _close_after(
        database,
        lambda connection: ingest_private_seed(connection, seed),
    )
    print(
        f"Ingested private seed: {len(seed.people)} people, "
        f"{len(seed.relationships)} relationships"
    )


def _cohorts(args: argparse.Namespace) -> None:
    database = _existing_file(
        _required(args.database, "cohorts", "--database"),
        "database",
    )
    root_person_id = _required(
        args.root_person_id, "cohorts", "--root-person-id"
    )
    try:
        uuid.UUID(root_person_id)
    except ValueError as error:
        raise CliError(
            f"root person ID must be a UUID: {root_person_id}"
        ) from error

    result = _close_after(
        database,
        lambda connection: recompute_cohorts(connection, root_person_id),
    )
    counts = ", ".join(
        f"{code}={len(result.memberships[code])}" for code in COHORT_CODES
    )
    print(f"Recomputed cohorts for {root_person_id}: {counts}")


def _coverage(args: argparse.Namespace) -> None:
    database = _existing_file(
        _required(args.database, "coverage", "--database"),
        "database",
    )
    cohort = _required(args.cohort, "coverage", "--cohort")
    if cohort not in COHORT_CODES:
        raise CliError(
            f"cohort must be one of {', '.join(COHORT_CODES)}: {cohort}"
        )
    markdown = _output_file(
        _required(args.markdown, "coverage", "--markdown"),
        "Markdown output",
    )
    json_output = _output_file(
        _required(args.json, "coverage", "--json"),
        "JSON output",
    )
    if _same_path(markdown, json_output):
        raise CliError("Markdown and JSON outputs must be different paths")
    for output in (markdown, json_output):
        if _same_path(output, database):
            raise CliError("coverage output cannot replace the canonical database")

    connection = create_store(database)
    try:
        for output in (markdown, json_output):
            if _ingested_batch_collision(connection, output):
                raise CliError(f"coverage output cannot replace research batch input: {output}")
            if _registered_source_collision(connection, database, output):
                raise CliError(f"coverage output cannot replace registered source file: {output}")
        report = build_coverage_report(connection, cohort)
    finally:
        connection.close()
    markdown.write_text(
        render_coverage_markdown(report),
        encoding="utf-8",
    )
    json_output.write_text(
        render_coverage_json(report),
        encoding="utf-8",
    )
    print(
        f"Wrote cohort {cohort} coverage for "
        f"{report.metric('people').eligible} people: "
        f"{markdown}, {json_output}"
    )


def _ingest_research(args: argparse.Namespace) -> None:
    database = _existing_file(
        _required(args.database, "ingest-research", "--database"),
        "database",
    )
    root = _existing_directory(
        _required(args.root, "ingest-research", "--root"),
        "research root",
    )
    input_path = _existing_file(
        _required(args.input, "ingest-research", "INPUT"),
        "research batch",
    )
    if _same_path(input_path, database):
        raise CliError("research batch and canonical database must be different")

    input_hash_before = sha256_file(input_path)
    batch = load_research_batch(input_path)
    if sha256_file(input_path) != input_hash_before:
        raise CliError(f"research batch changed while being read: {input_path}")
    for source in batch.sources:
        if source.file is None:
            continue
        source_path = root / Path(
            *source.file.path.replace("\\", "/").split("/")
        )
        if _same_path(source_path, database):
            raise CliError(
                "research source file and canonical database must be different: "
                f"{source_path}"
            )

    result = _close_after(
        database,
        lambda connection: ingest_research_batch(
            connection,
            batch,
            root,
            batch_path=input_path,
        ),
    )
    if sha256_file(input_path) != input_hash_before:
        raise CliError(f"research batch changed during ingestion: {input_path}")
    if result.repeated:
        print(
            f"Research batch {batch.batch_id} was already ingested; "
            "repeated batch made no changes"
        )
        return
    print(
        f"Ingested research batch {batch.batch_id}: "
        f"{result.people_added} people, {result.sources_added} sources, "
        f"{result.files_added} files, {result.assertions_added} assertions, "
        f"{result.relationships_added} relationships"
    )


def _registered_source_collision(
    connection: sqlite3.Connection,
    database: Path,
    output: Path,
) -> bool:
    registered_paths = connection.execute(
        """
        SELECT resolved_path
        FROM source_file_location
        ORDER BY source_file_location_id
        """
    ).fetchall()
    if any(
        _same_path(output, Path(str(resolved_path)))
        for (resolved_path,) in registered_paths
    ):
        return True

    rows = connection.execute(
        """
        SELECT file.sha256, file.local_path
        FROM source_file AS file
        WHERE NOT EXISTS (
            SELECT 1
            FROM source_file_location AS location
            WHERE location.source_file_id = file.source_file_id
        )
        ORDER BY file.source_file_id
        """
    ).fetchall()
    bases = (Path.cwd(), *database.resolve().parents)
    for sha256, local_path in rows:
        stored_path = Path(str(local_path))
        candidates = (
            (stored_path,)
            if stored_path.is_absolute()
            else tuple(base / stored_path for base in bases)
        )
        if any(_same_path(output, candidate) for candidate in candidates):
            return True
        if output.exists() and sha256_file(output) == sha256:
            return True
    return False


def _ingested_batch_collision(
    connection: sqlite3.Connection,
    output: Path,
) -> bool:
    registered_paths = connection.execute(
        """
        SELECT resolved_path
        FROM research_batch_input
        ORDER BY research_batch_input_id
        """
    ).fetchall()
    if any(
        _same_path(output, Path(str(resolved_path)))
        for (resolved_path,) in registered_paths
    ):
        return True
    if not output.exists() or not output.is_file():
        return False
    try:
        batch = load_research_batch(output)
    except (OSError, ValueError):
        return False
    row = connection.execute(
        """
        SELECT manifest_sha256
        FROM snapshot
        WHERE snapshot_id = ?
          AND source_system = 'research_batch'
        """,
        (f"research-batch-{batch.batch_id}",),
    ).fetchone()
    return row is not None and row[0] == batch.digest()


def _research_report(args: argparse.Namespace) -> None:
    database = _existing_file(
        _required(args.database, "research-report", "--database"),
        "database",
    )
    title = _required(
        args.question_title,
        "research-report",
        "--question-title",
    )
    output_dir = _existing_directory(
        _required(args.output_dir, "research-report", "--output-dir"),
        "research report output directory",
    )

    connection = create_store(database)
    try:
        state = load_research_state(connection, title)
        outputs = render_research_outputs(state)
        if args.html:
            from genealogy.report_page import render_research_page
            outputs["index.html"] = render_research_page(state, outputs)
        if any(not isinstance(content, str) for content in outputs.values()):
            raise CliError("research report renderer returned a non-text output")
        output_paths = {
            name: _output_file(output_dir / name, "research report output")
            for name in outputs
        }
        for output in output_paths.values():
            if _same_path(output, database):
                raise CliError(
                    f"research report output cannot replace database: {output}"
                )
            if _ingested_batch_collision(connection, output):
                raise CliError(
                    "research report output cannot replace research batch input: "
                    f"{output}"
                )
            if _registered_source_collision(connection, database, output):
                raise CliError(
                    "research report output cannot replace registered source file: "
                    f"{output}"
                )
    finally:
        connection.close()

    for name, content in outputs.items():
        output_paths[name].write_text(content, encoding="utf-8")
    print(f"Wrote five research outputs{' and an HTML reader' if args.html else ''} for {title}: {output_dir}")


def _demo(args: argparse.Namespace) -> None:
    from genealogy.demo import make_demo
    result = make_demo(Path(args.output))
    print(f"Created the wholly invented demo. Open this file in your browser: {result}")


_COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "demo": _demo,
    "manifest": _manifest,
    "init-store": _init_store,
    "ingest-rm": _ingest_rm,
    "ingest-seed": _ingest_seed,
    "cohorts": _cohorts,
    "coverage": _coverage,
    "ingest-research": _ingest_research,
    "research-report": _research_report,
}

_USER_ERRORS = (
    OSError,
    RootsMagicExtractionError,
    RootsMagicSchemaError,
    SeedValidationError,
    SnapshotConflictError,
    ValueError,
    sqlite3.Error,
)


def _one_line(message: object) -> str:
    return " ".join(str(message).splitlines()).strip() or "operation failed"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and convert user-correctable errors to an exit status."""
    try:
        args = _parser().parse_args(argv)
        if args.command is None:
            raise CliError("a command is required")
        _COMMANDS[args.command](args)
    except _USER_ERRORS as error:
        print(f"error: {_one_line(error)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
