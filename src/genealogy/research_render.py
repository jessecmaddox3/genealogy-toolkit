"""Load and render deterministic living outputs for one research question."""

from __future__ import annotations

import json
import sqlite3


_COMPLETED_SEARCH_STATUSES = frozenset(
    {"downloaded", "processed", "no_relevant_result", "rejected"}
)
_CONFLICT_WEIGHT = {"low": 0, "medium": 1, "high": 2}


def _parse_json_field(
    value: object,
    *,
    field: str,
    default: object,
) -> object:
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValueError(f"research question has invalid {field} JSON") from error


def _source_files(
    connection: sqlite3.Connection,
    source_id: int,
) -> list[dict[str, object]]:
    columns = (
        "source_file_id",
        "sha256",
        "size_bytes",
        "local_path",
        "original_filename",
        "rights_label",
        "ocr_status",
        "transcription_status",
    )
    rows = connection.execute(
        """
        SELECT file.source_file_id, file.sha256, file.size_bytes,
               file.local_path, file.original_filename, file.rights_label,
               file.ocr_status, file.transcription_status
        FROM source_file_link AS link
        JOIN source_file AS file
          ON file.source_file_id = link.source_file_id
        WHERE link.source_id = ?
        ORDER BY file.source_file_id
        """,
        (source_id,),
    ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _research_sources(
    connection: sqlite3.Connection,
    title: str,
) -> list[dict[str, object]]:
    columns = (
        "source_id",
        "source_key",
        "snapshot_id",
        "source_type",
        "repository",
        "collection_name",
        "record_title",
        "jurisdiction",
        "volume",
        "page",
        "url",
        "accessed_at",
        "evidence_tier",
        "citation_text",
    )
    rows = connection.execute(
        """
        WITH latest_source AS (
            SELECT source_key.source_key,
                   MAX(source_key.source_id) AS source_id
            FROM research_source_key AS source_key
            JOIN snapshot
              ON snapshot.snapshot_id = source_key.snapshot_id
            WHERE snapshot.source_system = 'research_batch'
              AND snapshot.import_scope = ?
            GROUP BY source_key.source_key
        )
        SELECT source.source_id, source_key.source_key,
               source.snapshot_id, source.source_type,
               source.repository, source.collection_name,
               source.record_title, source.jurisdiction, source.volume,
               source.page, source.url, source.accessed_at,
               source.evidence_tier, source.citation_text
        FROM latest_source AS source_key
        JOIN source
          ON source.source_id = source_key.source_id
        ORDER BY source.source_id
        """,
        (title,),
    ).fetchall()
    sources: list[dict[str, object]] = []
    for row in rows:
        source = dict(zip(columns, row, strict=True))
        source["files"] = _source_files(connection, int(source["source_id"]))
        sources.append(source)
    return sources


def load_research_state(
    connection: sqlite3.Connection,
    title: str,
) -> dict[str, object]:
    """Load the one research question whose title exactly matches ``title``."""
    rows = connection.execute(
        """
        SELECT research_question_id, title, status, target_people_json,
               target_relationships_json, planned_searches, negative_results,
               current_conclusion, working_confidence, created_at, updated_at
        FROM research_question
        WHERE title = ?
        ORDER BY research_question_id
        LIMIT 2
        """,
        (title,),
    ).fetchall()
    if not rows:
        raise ValueError(f"research question not found: {title}")
    if len(rows) != 1:
        raise ValueError(
            f"multiple research questions match exact title: {title}"
        )

    row = rows[0]
    state: dict[str, object] = {
        "research_question_id": row[0],
        "title": row[1],
        "status": row[2],
        "target_people": _parse_json_field(
            row[3],
            field="target_people_json",
            default=[],
        ),
        "target_relationships": _parse_json_field(
            row[4],
            field="target_relationships_json",
            default=[],
        ),
        "planned_searches": _parse_json_field(
            row[5],
            field="planned_searches",
            default=[],
        ),
        "negative_results": _parse_json_field(
            row[6],
            field="negative_results",
            default=[],
        ),
        "current_conclusion": _parse_json_field(
            row[7],
            field="current_conclusion",
            default={},
        ),
        "working_confidence": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }
    state["sources"] = _research_sources(connection, title)
    return state


def _list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _text(value: object, fallback: str = "Not recorded") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _cell(value: object) -> str:
    return _text(value).replace("|", "\\|").replace("\n", " ")


def _source_keys(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "Not recorded"
    return ", ".join(str(key) for key in value)


def _render_direct_line(state: dict[str, object]) -> str:
    conclusion = _dict(state.get("current_conclusion"))
    anchors = _list(conclusion.get("line_anchor"))
    lines = [
        "# Direct-Line Audit",
        (
            "> **TL;DR:** The recent line is accepted as a working line; "
            "middle links remain lightly checked and need stronger documentary support."
        ),
        "",
        "## Research Question",
        "",
        f"**{_text(state.get('title'))}**",
        "",
        _text(conclusion.get("summary")),
        "",
        "## Line Anchor",
        "",
        (
            "The rows retain the research-batch order so the working line reads "
            "in the sequence selected by the researcher."
        ),
        "",
        "| Order | Person key | Canonical person ID | Confidence | Basis | Note |",
        "|---:|---|---|---|---|---|",
    ]
    for index, anchor in enumerate(anchors, start=1):
        lines.append(
            "| "
            + " | ".join(
                (
                    str(index),
                    _cell(anchor.get("person_key")),
                    _cell(anchor.get("person_id")),
                    _cell(anchor.get("confidence")),
                    _cell(anchor.get("basis")),
                    _cell(anchor.get("note")),
                )
            )
            + " |"
        )
    if not anchors:
        lines.append("| 1 | Not recorded | Not recorded | Not recorded | Not recorded | Not recorded |")
    return "\n".join(lines) + "\n"


def _next_decisive_evidence(state: dict[str, object]) -> str:
    searches = _list(state.get("planned_searches"))
    unresolved = [
        search
        for search in searches
        if search.get("status") not in _COMPLETED_SEARCH_STATUSES
    ]
    if not unresolved:
        return "No unresolved research search is currently queued."
    first = unresolved[0]
    return _text(first.get("expected_value"))


def _render_dossier(state: dict[str, object]) -> str:
    conclusion = _dict(state.get("current_conclusion"))
    timeline = _list(conclusion.get("timeline"))
    associates = _list(conclusion.get("associates"))
    sources = _list(state.get("sources"))
    negatives = _list(state.get("negative_results"))
    lines = [
        f"# Person Dossier: {_text(state.get('title'))}",
        (
            "> **TL;DR:** Current identity: "
            f"{_text(conclusion.get('summary'))} "
            f"Next decisive evidence: {_next_decisive_evidence(state)}"
        ),
        "",
        "## Timeline",
        "",
        (
            "The chronology retains the batch order, including deliberate "
            "research sequencing that may differ from date order."
        ),
        "",
        "| Date | Place | Event | Source keys |",
        "|---|---|---|---|",
    ]
    for entry in timeline:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(entry.get("date_text")),
                    _cell(entry.get("place_text")),
                    _cell(entry.get("event_text")),
                    _cell(_source_keys(entry.get("source_keys"))),
                )
            )
            + " |"
        )
    if not timeline:
        lines.append("| Not recorded | Not recorded | Not recorded | Not recorded |")

    lines.extend(
        [
            "",
            "## Associates",
            "",
            (
                "Associates preserve named witnesses, neighbors, and other "
                "connections that may distinguish identities."
            ),
            "",
            "| Name | Relationship | Source keys | Note |",
            "|---|---|---|---|",
        ]
    )
    for associate in associates:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(associate.get("name")),
                    _cell(associate.get("relationship")),
                    _cell(_source_keys(associate.get("source_keys"))),
                    _cell(associate.get("note")),
                )
            )
            + " |"
        )
    if not associates:
        lines.append("| Not recorded | Not recorded | Not recorded | Not recorded |")

    lines.extend(
        [
            "",
            "## Cited Sources",
            "",
            (
                "These documentary sources are linked to the current question. "
                "File metadata identifies immutable local evidence when available."
            ),
            "",
        ]
    )
    if not sources:
        lines.append("- No cited sources are recorded.")
    for source in sources:
        source_id = _text(source.get("source_id"))
        title = _text(source.get("record_title"))
        citation = _text(source.get("citation_text"), "Citation not recorded")
        source_key = _text(source.get("source_key"))
        lines.append(
            f"- **{source_key} (source {source_id}): {title}.** {citation}"
        )
        files = _list(source.get("files"))
        for file in files:
            lines.append(
                "  - File: "
                f"`{_text(file.get('local_path'))}` "
                f"({_text(file.get('original_filename'))}, "
                f"SHA-256 `{_text(file.get('sha256'))}`, "
                f"rights `{_text(file.get('rights_label'))}`, "
                f"OCR `{_text(file.get('ocr_status'))}`, "
                "transcription "
                f"`{_text(file.get('transcription_status'))}`)"
            )

    lines.extend(
        [
            "",
            "## Negative Searches",
            "",
            (
                "Negative searches remain in the dossier so future work does "
                "not repeat a completed search."
            ),
            "",
        ]
    )
    if not negatives:
        lines.append("- No negative searches are recorded.")
    for search in negatives:
        lines.append(
            f"- **{_text(search.get('key'))}: No relevant result.** "
            f"{_text(search.get('result_summary'))} "
            f"Repository: {_text(search.get('repository'))}; "
            f"collection: {_text(search.get('collection'))}; "
            f"target: {_text(search.get('target'))}; "
            f"locator: {_text(search.get('locator'))}."
        )
    return "\n".join(lines) + "\n"


def _hypothesis_evidence(
    hypothesis: dict[str, object],
    direction: str,
) -> str:
    evidence = [
        item
        for item in _list(hypothesis.get("evidence"))
        if item.get("direction") == direction
    ]
    if not evidence:
        return "None recorded"
    return "; ".join(
        (
            f"{_text(item.get('rationale'))} "
            f"[{_text(item.get('source_key'))}, {_text(item.get('weight'))}]"
        )
        for item in evidence
    )


def _strongest_conflict(hypotheses: list[dict[str, object]]) -> str:
    conflicts = [
        item
        for hypothesis in hypotheses
        for item in _list(hypothesis.get("evidence"))
        if item.get("direction") == "conflicts"
    ]
    if not conflicts:
        return "No conflicting evidence is recorded."
    strongest = sorted(
        conflicts,
        key=lambda item: (
            -_CONFLICT_WEIGHT.get(str(item.get("weight")), -1),
            str(item.get("source_key", "")),
            str(item.get("rationale", "")),
        ),
    )[0]
    return (
        f"{_text(strongest.get('rationale'))} "
        f"[{_text(strongest.get('source_key'))}, "
        f"{_text(strongest.get('weight'))}]"
    )


def _render_hypotheses(state: dict[str, object]) -> str:
    conclusion = _dict(state.get("current_conclusion"))
    hypotheses = sorted(
        _list(conclusion.get("hypotheses")),
        key=lambda item: (
            int(item.get("rank", 0)),
            str(item.get("key", "")),
        ),
    )
    if hypotheses:
        leader = hypotheses[0]
        leader_text = (
            f"{_text(leader.get('statement'))} "
            f"(rank {_text(leader.get('rank'))}, key {_text(leader.get('key'))})"
        )
    else:
        leader_text = "No hypothesis is recorded"
    lines = [
        "# Hypothesis Matrix",
        (
            f"> **TL;DR:** Current leading hypothesis: {leader_text}. "
            f"Strongest conflict: {_strongest_conflict(hypotheses)}"
        ),
        "",
        "## Ranked Hypotheses",
        "",
        (
            "Hypotheses are ordered by rank and then key. Evidence remains "
            "separated into support, conflict, and context."
        ),
        "",
        (
            "| Rank | Key | Status | Hypothesis | Supporting evidence | "
            "Conflicting evidence | Context |"
        ),
        "|---:|---|---|---|---|---|---|",
    ]
    for hypothesis in hypotheses:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(hypothesis.get("rank")),
                    _cell(hypothesis.get("key")),
                    _cell(hypothesis.get("status")),
                    _cell(hypothesis.get("statement")),
                    _cell(_hypothesis_evidence(hypothesis, "supports")),
                    _cell(_hypothesis_evidence(hypothesis, "conflicts")),
                    _cell(_hypothesis_evidence(hypothesis, "context")),
                )
            )
            + " |"
        )
    if not hypotheses:
        lines.append(
            "| 0 | Not recorded | Not recorded | Not recorded | "
            "None recorded | None recorded | None recorded |"
        )
    return "\n".join(lines) + "\n"


def _actionable_searches(state: dict[str, object]) -> list[dict[str, object]]:
    return sorted(
        (
            search
            for search in _list(state.get("planned_searches"))
            if search.get("required_action") != "none"
            and search.get("status") not in _COMPLETED_SEARCH_STATUSES
        ),
        key=lambda item: (
            str(item.get("required_action", "")),
            str(item.get("key", "")),
        ),
    )


def _render_actions(state: dict[str, object]) -> str:
    searches = _actionable_searches(state)
    count = len(searches)
    noun = "task requires" if count == 1 else "tasks require"
    lines = [
        "# Action Queue",
        f"> **TL;DR:** {count} {noun} your attention.",
        "",
        "## Exact User Actions",
        "",
        (
            "Only unresolved tasks requiring the researcher appear here. Each row gives "
            "the precise action, target, locator, destination, and expected value."
        ),
        "",
        (
            "| Required action | Search key | Status | Repository and collection | "
            "Target | Locator | URL | Save to | Expected research value |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for search in searches:
        repository = (
            f"{_text(search.get('repository'))}: "
            f"{_text(search.get('collection'))}"
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(search.get("required_action")),
                    _cell(search.get("key")),
                    _cell(search.get("status")),
                    _cell(repository),
                    _cell(search.get("target")),
                    _cell(search.get("locator")),
                    _cell(search.get("url")),
                    _cell(search.get("destination_path")),
                    _cell(search.get("expected_value")),
                )
            )
            + " |"
        )
    if not searches:
        lines.append(
            "| none | Not applicable | Not applicable | Not applicable | "
            "Not applicable | Not applicable | Not applicable | "
            "Not applicable | Not applicable |"
        )
    return "\n".join(lines) + "\n"


def render_research_outputs(state: dict[str, object]) -> dict[str, str]:
    """Render exactly the five deterministic research living outputs."""
    return {
        "direct-line-audit.md": _render_direct_line(state),
        "person-dossier.md": _render_dossier(state),
        "hypothesis-matrix.md": _render_hypotheses(state),
        "action-queue.md": _render_actions(state),
        "research-state.json": (
            json.dumps(
                state,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ),
    }
