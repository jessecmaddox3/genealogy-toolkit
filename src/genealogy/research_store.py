"""Atomic ingestion for immutable documentary research batches."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from genealogy.integrity import require_consistent_working_graph
from genealogy.identity import (
    add_global_identifier,
    find_global_identifier_person,
    resolve_exact_person,
)
from genealogy.research_records import (
    ResearchBatch,
    ResearchFile,
    validate_research_file_metadata,
)
from genealogy.store import SnapshotConflictError


@dataclass(frozen=True, slots=True)
class ResearchIngestResult:
    """Counts added by one research-batch ingestion."""

    snapshot_id: str
    people_added: int
    sources_added: int
    files_added: int
    assertions_added: int
    relationships_added: int
    repeated: bool


@dataclass(frozen=True, slots=True)
class _PreflightFile:
    metadata: ResearchFile
    requested_path: str
    resolved_path: Path
    local_path: str
    sha256: str
    size_bytes: int


_OCR_RANK = {
    "not_started": 0,
    "raw": 1,
    "corrected": 2,
}
_TRANSCRIPTION_RANK = {
    "not_started": 0,
    "partial": 1,
    "complete": 2,
}


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _fingerprint(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _resolve_file(root: Path, relative_path: str, context: str) -> Path:
    project_path = Path(*relative_path.replace("\\", "/").split("/"))
    try:
        resolved = (root / project_path).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"{context} is not an accessible regular file") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{context} must stay below project root") from error
    if not resolved.is_file():
        raise ValueError(f"{context} must be a regular file")
    return resolved


def _require_private_path(
    root: Path,
    resolved: Path,
    file: ResearchFile,
    context: str,
) -> None:
    if file.rights_label == "public_domain":
        return
    private_root = (root / "data" / "private").resolve(strict=False)
    try:
        resolved.relative_to(private_root)
    except ValueError as error:
        raise ValueError(
            f"{context} with rights {file.rights_label} must stay below "
            "data/private"
        ) from error


def _preflight_files(
    batch: ResearchBatch,
    root: Path,
) -> dict[str, _PreflightFile]:
    files: dict[str, _PreflightFile] = {}
    for source in batch.sources:
        if source.file is None:
            continue
        validate_research_file_metadata(source.file)
        resolved = _resolve_file(
            root,
            source.file.path,
            f"source {source.key} file",
        )
        _require_private_path(
            root,
            resolved,
            source.file,
            f"source {source.key} file",
        )
        sha256, size_bytes = _fingerprint(resolved)
        files[source.key] = _PreflightFile(
            metadata=source.file,
            requested_path=source.file.path,
            resolved_path=resolved,
            local_path=resolved.relative_to(root).as_posix(),
            sha256=sha256,
            size_bytes=size_bytes,
        )
    return files


def _verify_preflight_file(file: _PreflightFile, root: Path) -> None:
    current_path = _resolve_file(root, file.requested_path, "research source file")
    if current_path != file.resolved_path:
        raise ValueError(f"research source file {file.requested_path} changed after preflight")
    sha256, size_bytes = _fingerprint(current_path)
    if sha256 != file.sha256 or size_bytes != file.size_bytes:
        raise ValueError(f"research source file {file.requested_path} changed after preflight")


def _existing_snapshot_digest(
    connection: sqlite3.Connection,
    snapshot_id: str,
) -> str | None:
    row = connection.execute(
        "SELECT manifest_sha256 FROM snapshot WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    return None if row is None else row[0]


def _check_snapshot_identity(
    connection: sqlite3.Connection,
    snapshot_id: str,
    digest: str,
) -> bool:
    existing = _existing_snapshot_digest(connection, snapshot_id)
    if existing is None:
        return False
    if existing != digest:
        raise SnapshotConflictError(
            f"snapshot {snapshot_id} already has manifest {existing}; "
            f"refusing different hash {digest}"
        )
    return True


def _empty_result(snapshot_id: str) -> ResearchIngestResult:
    return ResearchIngestResult(
        snapshot_id=snapshot_id,
        people_added=0,
        sources_added=0,
        files_added=0,
        assertions_added=0,
        relationships_added=0,
        repeated=True,
    )


def _insert_snapshot(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
    digest: str,
) -> None:
    connection.execute(
        """
        INSERT INTO snapshot(
            snapshot_id, manifest_sha256, source_system, import_scope,
            source_person_count, source_family_count,
            source_child_link_count, source_event_count, source_place_count
        ) VALUES (?, ?, 'research_batch', ?, ?, ?, ?, ?, 0)
        """,
        (
            snapshot_id,
            digest,
            batch.question.title,
            len(batch.people),
            len(batch.relationships),
            len(batch.relationships),
            len(batch.assertions),
        ),
    )


def _insert_sources(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
) -> dict[str, int]:
    source_ids: dict[str, int] = {}
    for source in batch.sources:
        cursor = connection.execute(
            """
            INSERT INTO source(
                snapshot_id, source_type, repository, collection_name,
                record_title, jurisdiction, volume, page, url, accessed_at,
                evidence_tier, citation_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                source.source_type,
                source.repository,
                source.collection_name,
                source.record_title,
                source.jurisdiction,
                source.volume,
                source.page,
                source.url,
                source.accessed_at,
                source.evidence_tier,
                source.citation_text,
            ),
        )
        source_ids[source.key] = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO research_source_key(snapshot_id, source_key, source_id)
            VALUES (?, ?, ?)
            """,
            (snapshot_id, source.key, cursor.lastrowid),
        )
    return source_ids


def _upsert_assertion_conclusion(
    connection: sqlite3.Connection,
    *,
    assertion_id: int,
    subject_id: str,
    predicate: str,
    confidence: str,
    rationale: str,
) -> None:
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES ('person', ?, ?, ?, NULL, ?, ?)
        ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
            chosen_assertion_id = excluded.chosen_assertion_id,
            chosen_relationship_assertion_id = NULL,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (subject_id, predicate, assertion_id, confidence, rationale),
    )


def _insert_people(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
    source_ids: dict[str, int],
) -> tuple[dict[str, str], int, int]:
    person_ids: dict[str, str] = {}
    people_added = 0
    assertions_added = 0
    for person in batch.people:
        identifiers = {"research_key": f"research:{person.key}"}
        if person.familysearch_id is not None:
            identifiers["familysearch"] = person.familysearch_id
        existing_identifier_people = {
            existing_person
            for system, value in identifiers.items()
            if (
                existing_person := find_global_identifier_person(
                    connection,
                    system,
                    value,
                )
            )
            is not None
        }
        person_id = resolve_exact_person(connection, identifiers)
        exists = connection.execute(
            "SELECT 1 FROM person WHERE person_id = ?",
            (person_id,),
        ).fetchone()
        if exists is None:
            if existing_identifier_people:
                raise ValueError(
                    f"identifier for {person.key} references missing canonical person "
                    f"{person_id}"
                )
            connection.execute(
                "INSERT INTO person(person_id, living, private) VALUES (?, 0, 0)",
                (person_id,),
            )
            people_added += 1
        person_ids[person.key] = person_id
        for system, value in identifiers.items():
            add_global_identifier(
                connection,
                person_id=person_id,
                system=system,
                value=value,
                snapshot_id=snapshot_id,
            )

        cursor = connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, subject_person_id, predicate,
                value_text, raw_value, parsed_value, snapshot_id, source_id,
                raw_external_assertion_id, raw_external_owner_id, is_private
            ) VALUES (
                'person', ?, ?, 'person.primary_name', ?, ?, ?, ?, ?, ?, ?, 0
            )
            """,
            (
                person_id,
                person_id,
                person.display_name,
                person.display_name,
                _stable_json({"display_name": person.display_name}),
                snapshot_id,
                source_ids[person.source_key],
                f"research-name:{person.key}",
                person.key,
            ),
        )
        _upsert_assertion_conclusion(
            connection,
            assertion_id=cursor.lastrowid,
            subject_id=person_id,
            predicate="person.primary_name",
            confidence=person.name_confidence,
            rationale=person.name_rationale,
        )
        assertions_added += 1
    return person_ids, people_added, assertions_added


def _forward_status(
    current: str,
    incoming: str,
    rank: dict[str, int],
) -> str:
    if current == "not_applicable" or incoming == current:
        return current
    if incoming == "not_applicable":
        return incoming
    if rank[incoming] > rank[current]:
        return incoming
    return current


def _stored_file_preflight(
    connection: sqlite3.Connection,
    root: Path,
    row: tuple[object, ...],
) -> _PreflightFile:
    source_file_id, sha256, size_bytes, local_path, rights_label = row
    stored_path = str(local_path)
    resolved = _resolve_file(root, stored_path, f"stored source file {source_file_id}")
    actual_sha256, actual_size = _fingerprint(resolved)
    if actual_sha256 != sha256 or actual_size != size_bytes:
        raise ValueError(f"stored source file {source_file_id} no longer matches its hash")
    metadata = ResearchFile(
        path=stored_path,
        original_filename=resolved.name,
        rights_label=str(rights_label),  # type: ignore[arg-type]
        ocr_status="not_started",
        transcription_status="not_started",
    )
    validate_research_file_metadata(metadata)
    _require_private_path(
        root,
        resolved,
        metadata,
        f"stored source file {source_file_id}",
    )
    return _PreflightFile(
        metadata=metadata,
        requested_path=stored_path,
        resolved_path=resolved,
        local_path=stored_path,
        sha256=str(sha256),
        size_bytes=int(size_bytes),
    )


def _insert_files(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    root: Path,
    source_ids: dict[str, int],
    files: dict[str, _PreflightFile],
) -> tuple[int, list[_PreflightFile]]:
    files_added = 0
    stored_files_to_verify: dict[int, _PreflightFile] = {}
    for source in batch.sources:
        file = files.get(source.key)
        if file is None:
            continue
        existing = connection.execute(
            """
            SELECT source_file_id, sha256, size_bytes, local_path,
                   rights_label, ocr_status, transcription_status
            FROM source_file
            WHERE sha256 = ?
            """,
            (file.sha256,),
        ).fetchone()
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO source_file(
                    sha256, size_bytes, local_path, original_filename,
                    rights_label, ocr_status, transcription_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file.sha256,
                    file.size_bytes,
                    file.local_path,
                    file.metadata.original_filename,
                    file.metadata.rights_label,
                    file.metadata.ocr_status,
                    file.metadata.transcription_status,
                ),
            )
            source_file_id = cursor.lastrowid
            files_added += 1
        else:
            source_file_id = existing[0]
            stored_file = _stored_file_preflight(
                connection,
                root,
                existing[:5],
            )
            stored_files_to_verify[source_file_id] = stored_file
            _require_private_path(
                root,
                file.resolved_path,
                stored_file.metadata,
                f"source {source.key} file",
            )
            ocr_status = _forward_status(
                existing[5],
                file.metadata.ocr_status,
                _OCR_RANK,
            )
            transcription_status = _forward_status(
                existing[6],
                file.metadata.transcription_status,
                _TRANSCRIPTION_RANK,
            )
            connection.execute(
                """
                UPDATE source_file
                SET ocr_status = ?, transcription_status = ?
                WHERE source_file_id = ?
                  AND (ocr_status != ? OR transcription_status != ?)
                """,
                (
                    ocr_status,
                    transcription_status,
                    source_file_id,
                    ocr_status,
                    transcription_status,
                ),
            )
        connection.execute(
            """
            INSERT INTO source_file_location(
                source_file_id, resolved_path, acquisition_root
            ) VALUES (?, ?, ?)
            ON CONFLICT(source_file_id, resolved_path) DO NOTHING
            """,
            (
                source_file_id,
                str(file.resolved_path),
                str(root),
            ),
        )
        connection.execute(
            """
            INSERT INTO source_file_link(source_file_id, source_id)
            VALUES (?, ?)
            """,
            (source_file_id, source_ids[source.key]),
        )
    return files_added, list(stored_files_to_verify.values())


def _insert_documentary_assertions(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
    person_ids: dict[str, str],
    source_ids: dict[str, int],
) -> int:
    for assertion in batch.assertions:
        person_id = person_ids[assertion.person_key]
        cursor = connection.execute(
            """
            INSERT INTO assertion(
                subject_type, subject_id, subject_person_id, predicate,
                value_text, raw_value, parsed_value, snapshot_id, source_id,
                raw_external_assertion_id, raw_external_owner_id, is_private
            ) VALUES ('person', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                person_id,
                person_id,
                assertion.predicate,
                assertion.value_text,
                assertion.raw_value,
                (
                    None
                    if assertion.parsed_value is None
                    else _stable_json(assertion.parsed_value)
                ),
                snapshot_id,
                source_ids[assertion.source_key],
                assertion.key,
                assertion.person_key,
            ),
        )
        _upsert_assertion_conclusion(
            connection,
            assertion_id=cursor.lastrowid,
            subject_id=person_id,
            predicate=assertion.predicate,
            confidence=assertion.confidence,
            rationale=assertion.rationale,
        )
    return len(batch.assertions)


def _upsert_relationship_conclusion(
    connection: sqlite3.Connection,
    *,
    relationship_assertion_id: int,
    child_id: str,
    parent_id: str,
    role: str | None,
    confidence: str,
    rationale: str,
) -> None:
    subject_id = str(relationship_assertion_id)
    connection.execute(
        """
        INSERT INTO conclusion(
            subject_type, subject_id, predicate, chosen_assertion_id,
            chosen_relationship_assertion_id, confidence, rationale
        ) VALUES ('relationship', ?, 'parent_child', NULL, ?, ?, ?)
        ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
            chosen_assertion_id = NULL,
            chosen_relationship_assertion_id =
                excluded.chosen_relationship_assertion_id,
            confidence = excluded.confidence,
            rationale = excluded.rationale,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            subject_id,
            relationship_assertion_id,
            confidence,
            rationale,
        ),
    )


def _insert_relationships(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
    person_ids: dict[str, str],
    source_ids: dict[str, int],
) -> list[int]:
    relationship_ids: list[int] = []
    # A batch states the complete new set of current claims for each mentioned
    # explicit parent slot (or each unspecified parent pair). Retire prior batch
    # conclusions once, then retain every new claim irrespective of confidence.
    # Raw assertions are immutable; a new working view never deletes evidence.
    for relationship in batch.relationships:
        connection.execute("""
            DELETE FROM conclusion WHERE conclusion_id IN (
                SELECT c.conclusion_id FROM conclusion c JOIN relationship_assertion r
                  ON r.relationship_assertion_id = c.chosen_relationship_assertion_id
                WHERE r.predicate = 'parent_child' AND r.object_person_id = ?
                  AND COALESCE(r.role, '') = COALESCE(?, '')
                  AND (? IS NOT NULL OR r.subject_person_id = ?)
            )
        """, (person_ids[relationship.child_key], relationship.role, relationship.role,
              person_ids[relationship.parent_key]))
    for relationship in batch.relationships:
        parent_id = person_ids[relationship.parent_key]
        child_id = person_ids[relationship.child_key]
        if parent_id == child_id:
            raise ValueError(f"relationship {relationship.key}: exact identity matching makes a person their own parent; the batch was not imported")
        cursor = connection.execute(
            """
            INSERT INTO relationship_assertion(
                subject_person_id, predicate, object_person_id, role,
                snapshot_id, source_id, raw_external_relationship_id,
                raw_external_family_id, raw_external_child_link_id
            ) VALUES (?, 'parent_child', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent_id,
                child_id,
                relationship.role,
                snapshot_id,
                source_ids[relationship.source_key],
                f"research:{relationship.key}",
                f"research-family:{relationship.child_key}",
                relationship.key,
            ),
        )
        relationship_id = cursor.lastrowid
        relationship_ids.append(relationship_id)
        _upsert_relationship_conclusion(
            connection,
            relationship_assertion_id=relationship_id,
            child_id=child_id,
            parent_id=parent_id,
            role=relationship.role,
            confidence=relationship.confidence,
            rationale=relationship.rationale,
        )
    return relationship_ids


def _question_current_conclusion(
    batch: ResearchBatch,
    person_ids: dict[str, str],
) -> dict[str, object]:
    line_anchor = []
    for anchor in batch.question.line_anchor:
        value = asdict(anchor)
        value["person_id"] = person_ids[anchor.person_key]
        line_anchor.append(value)
    return {
        "summary": batch.question.summary,
        "line_anchor": line_anchor,
        "timeline": [asdict(entry) for entry in batch.question.timeline],
        "associates": [asdict(entry) for entry in batch.question.associates],
        "hypotheses": [
            asdict(hypothesis) for hypothesis in batch.question.hypotheses
        ],
    }


def _upsert_question(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    person_ids: dict[str, str],
    relationship_ids: list[int],
) -> None:
    planned_searches = [
        asdict(search)
        for search in batch.question.searches
        if search.status != "no_relevant_result"
    ]
    negative_results = [
        asdict(search)
        for search in batch.question.searches
        if search.status == "no_relevant_result"
    ]
    connection.execute(
        """
        INSERT INTO research_question(
            title, status, target_people_json, target_relationships_json,
            planned_searches, negative_results, current_conclusion
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(title) DO UPDATE SET
            status = excluded.status,
            target_people_json = excluded.target_people_json,
            target_relationships_json = excluded.target_relationships_json,
            planned_searches = excluded.planned_searches,
            negative_results = excluded.negative_results,
            current_conclusion = excluded.current_conclusion,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            batch.question.title,
            batch.question.status,
            _stable_json(
                [person_ids[key] for key in batch.question.target_person_keys]
            ),
            _stable_json(relationship_ids),
            _stable_json(planned_searches),
            _stable_json(negative_results),
            _stable_json(_question_current_conclusion(batch, person_ids)),
        ),
    )


def _register_batch_input(
    connection: sqlite3.Connection,
    snapshot_id: str,
    root: Path,
    batch_path: Path | None,
) -> None:
    if batch_path is None:
        return
    try:
        resolved = batch_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("research batch input is not accessible") from error
    if not resolved.is_file():
        raise ValueError("research batch input must be a regular file")
    connection.execute(
        """
        INSERT INTO research_batch_input(
            snapshot_id, resolved_path, acquisition_root
        ) VALUES (?, ?, ?)
        ON CONFLICT(snapshot_id, resolved_path) DO NOTHING
        """,
        (snapshot_id, str(resolved), str(root)),
    )


def _backfill_repeated_source_locations(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
    root: Path,
) -> None:
    source_rows = connection.execute(
        """
        SELECT source_id
        FROM source
        WHERE snapshot_id = ?
        ORDER BY source_id
        """,
        (snapshot_id,),
    ).fetchall()
    if len(source_rows) != len(batch.sources):
        return
    for source, (source_id,) in zip(batch.sources, source_rows, strict=True):
        if source.file is None:
            continue
        linked = connection.execute(
            """
            SELECT source_file_id
            FROM source_file_link
            WHERE source_id = ?
            ORDER BY source_file_id
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if linked is None:
            continue
        project_path = Path(
            *source.file.path.replace("\\", "/").split("/")
        )
        try:
            resolved = (root / project_path).resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        connection.execute(
            """
            INSERT INTO source_file_location(
                source_file_id, resolved_path, acquisition_root
            ) VALUES (?, ?, ?)
            ON CONFLICT(source_file_id, resolved_path) DO NOTHING
            """,
            (linked[0], str(resolved), str(root)),
        )


def _backfill_repeated_source_keys(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    snapshot_id: str,
) -> None:
    for source in batch.sources:
        row = connection.execute(
            """
            SELECT source_id
            FROM source
            WHERE snapshot_id = ?
              AND source_type = ?
              AND record_title = ?
            """,
            (snapshot_id, source.source_type, source.record_title),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"stored research source {source.key} is missing from "
                f"{snapshot_id}"
            )
        source_id = int(row[0])
        connection.execute(
            """
            INSERT INTO research_source_key(snapshot_id, source_key, source_id)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_id, source_key) DO NOTHING
            """,
            (snapshot_id, source.key, source_id),
        )
        mapped = connection.execute(
            """
            SELECT source_id
            FROM research_source_key
            WHERE snapshot_id = ? AND source_key = ?
            """,
            (snapshot_id, source.key),
        ).fetchone()
        if mapped != (source_id,):
            raise ValueError(
                f"stored research source key {source.key} conflicts in "
                f"{snapshot_id}"
            )


def ingest_research_batch(
    connection: sqlite3.Connection,
    batch: ResearchBatch,
    root: Path,
    *,
    batch_path: Path | None = None,
) -> ResearchIngestResult:
    """Atomically ingest one immutable documentary research batch."""
    if connection.in_transaction:
        raise sqlite3.ProgrammingError(
            "ingest_research_batch requires a connection without an active transaction"
        )
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    snapshot_id = f"research-batch-{batch.batch_id}"
    digest = batch.digest()
    files = _preflight_files(batch, root)
    if _check_snapshot_identity(connection, snapshot_id, digest):
        connection.execute("BEGIN IMMEDIATE")
        try:
            _check_snapshot_identity(connection, snapshot_id, digest)
            _register_batch_input(
                connection,
                snapshot_id,
                root,
                batch_path,
            )
            _backfill_repeated_source_keys(
                connection,
                batch,
                snapshot_id,
            )
            _backfill_repeated_source_locations(
                connection,
                batch,
                snapshot_id,
                root,
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return _empty_result(snapshot_id)
    connection.execute("BEGIN IMMEDIATE")
    try:
        if _check_snapshot_identity(connection, snapshot_id, digest):
            _register_batch_input(
                connection,
                snapshot_id,
                root,
                batch_path,
            )
            _backfill_repeated_source_keys(
                connection,
                batch,
                snapshot_id,
            )
            _backfill_repeated_source_locations(
                connection,
                batch,
                snapshot_id,
                root,
            )
            connection.execute("COMMIT")
            return _empty_result(snapshot_id)
        _insert_snapshot(connection, batch, snapshot_id, digest)
        _register_batch_input(
            connection,
            snapshot_id,
            root,
            batch_path,
        )
        source_ids = _insert_sources(connection, batch, snapshot_id)
        person_ids, people_added, assertions_added = _insert_people(
            connection,
            batch,
            snapshot_id,
            source_ids,
        )
        files_added, stored_files = _insert_files(
            connection,
            batch,
            root,
            source_ids,
            files,
        )
        assertions_added += _insert_documentary_assertions(
            connection,
            batch,
            snapshot_id,
            person_ids,
            source_ids,
        )
        relationship_ids = _insert_relationships(
            connection,
            batch,
            snapshot_id,
            person_ids,
            source_ids,
        )
        require_consistent_working_graph(connection)
        _upsert_question(
            connection,
            batch,
            person_ids,
            relationship_ids,
        )
        for file in (*files.values(), *stored_files):
            _verify_preflight_file(file, root)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    return ResearchIngestResult(
        snapshot_id=snapshot_id,
        people_added=people_added,
        sources_added=len(source_ids),
        files_added=files_added,
        assertions_added=assertions_added,
        relationships_added=len(relationship_ids),
        repeated=False,
    )
