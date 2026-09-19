"""Deterministic living-output tests for documentary research state."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from genealogy.research_records import load_research_batch
from genealogy.research_render import load_research_state, render_research_outputs
from genealogy.research_store import ingest_research_batch
from genealogy.store import create_store
from tests.fixtures.research_batch import valid_research_payload


def _write_batch(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _ingest_payload(
    tmp_path: Path,
    payload: dict[str, object],
) -> sqlite3.Connection:
    record = (
        tmp_path
        / "data"
        / "private"
        / "research"
        / "example-workshop.pdf"
    )
    record.parent.mkdir(parents=True)
    record.write_bytes(b"fictional workshop register")
    batch = load_research_batch(_write_batch(tmp_path / "batch.json", payload))
    connection = create_store(tmp_path / "genealogy.sqlite")
    ingest_research_batch(connection, batch, tmp_path)
    return connection


def _ordered_payload() -> dict[str, object]:
    payload = valid_research_payload()
    question = payload["question"]
    assert isinstance(question, dict)
    question["line_anchor"] = [
        {
            "person_key": "example-parent",
            "basis": "First batch anchor",
            "confidence": "plausible_lead",
            "note": "FIRST LINE ANCHOR",
        },
        {
            "person_key": "example-child",
            "basis": "Second batch anchor",
            "confidence": "accepted_working",
            "note": "SECOND LINE ANCHOR",
        },
    ]
    question["timeline"] = [
        {
            "date_text": "abt 1800",
            "place_text": "Example County",
            "event_text": "FIRST TIMELINE EVENT",
            "source_keys": ["record-one"],
        },
        {
            "date_text": "abt 1700",
            "place_text": None,
            "event_text": "SECOND TIMELINE EVENT",
            "source_keys": ["profile-child"],
        },
    ]
    question["searches"] = [
        {
            "key": "z-paid",
            "repository": "Example Archive",
            "collection": "Example Workshop Registers",
            "target": "Paid packet Z",
            "locator": "Volume Z",
            "url": "https://example.invalid/z",
            "required_action": "approve_payment",
            "expected_value": "Resolve the parentage question.",
            "destination_path": "data/private/z.pdf",
            "status": "planned",
            "result_summary": None,
        },
        {
            "key": "a-paid",
            "repository": "Example Archive",
            "collection": "Example Workshop Registers",
            "target": "Paid packet A",
            "locator": "Volume A",
            "url": "https://example.invalid/a",
            "required_action": "approve_payment",
            "expected_value": "Compare apprentice ages.",
            "destination_path": "data/private/a.pdf",
            "status": "blocked",
            "result_summary": "Payment approval is required.",
        },
        {
            "key": "download-first",
            "repository": "Example Archive",
            "collection": "Example School Registers",
            "target": "Download school entry",
            "locator": "Book 1, page 2",
            "url": "https://example.invalid/school-entry",
            "required_action": "download",
            "expected_value": "Compare school entry dates.",
            "destination_path": "data/private/school-entry.pdf",
            "status": "accessible",
            "result_summary": None,
        },
        {
            "key": "completed-download",
            "repository": "Example Archive",
            "collection": "Example School Registers",
            "target": "Completed deed",
            "locator": None,
            "url": None,
            "required_action": "download",
            "expected_value": "Already obtained.",
            "destination_path": "data/private/complete.pdf",
            "status": "processed",
            "result_summary": "Complete.",
        },
        {
            "key": "automated-task",
            "repository": "Example Archive",
            "collection": "Example Index",
            "target": "Automated index search",
            "locator": None,
            "url": None,
            "required_action": "none",
            "expected_value": "Can run without Researcher.",
            "destination_path": None,
            "status": "planned",
            "result_summary": None,
        },
        {
            "key": "negative-search",
            "repository": "Example Archive",
            "collection": "Example Census",
            "target": "Search the county census",
            "locator": "Page range 1 to 20",
            "url": "https://example.invalid/census",
            "required_action": "none",
            "expected_value": "Find the household.",
            "destination_path": None,
            "status": "no_relevant_result",
            "result_summary": "No matching household appeared.",
        },
    ]
    question["hypotheses"] = [
        {
            "key": "later-key",
            "statement": "Later hypothesis",
            "rank": 2,
            "status": "unresolved",
            "evidence": [
                {
                    "source_key": "profile-child",
                    "direction": "context",
                    "weight": "low",
                    "rationale": "Context for the later hypothesis.",
                }
            ],
        },
        {
            "key": "leading-key",
            "statement": "Leading hypothesis",
            "rank": 1,
            "status": "active",
            "evidence": [
                {
                    "source_key": "record-one",
                    "direction": "supports",
                    "weight": "high",
                    "rationale": "The workshop register supports this identity.",
                },
                {
                    "source_key": "profile-child",
                    "direction": "conflicts",
                    "weight": "medium",
                    "rationale": "The profile gives a conflicting date.",
                },
            ],
        },
    ]
    return payload


def test_research_outputs_include_exact_files_sections_and_action_filtering(
    tmp_path: Path,
) -> None:
    """Dropping a living output or leaking completed searches breaks the handoff."""
    connection = _ingest_payload(tmp_path, _ordered_payload())

    state = load_research_state(connection, "Who were the example parents?")
    outputs = render_research_outputs(state)

    assert set(outputs) == {
        "direct-line-audit.md",
        "person-dossier.md",
        "hypothesis-matrix.md",
        "action-queue.md",
        "research-state.json",
    }
    for name, content in outputs.items():
        if name.endswith(".md"):
            assert content.splitlines()[1].startswith("> **TL;DR:**")
    assert "approve_payment" in outputs["action-queue.md"]
    assert "download-first" in outputs["action-queue.md"]
    assert "completed-download" not in outputs["action-queue.md"]
    assert "automated-task" not in outputs["action-queue.md"]
    assert "no_relevant_result" not in outputs["action-queue.md"]
    assert "No relevant result" in outputs["person-dossier.md"]
    assert "negative-search" in outputs["person-dossier.md"]
    assert "Timeline" in outputs["person-dossier.md"]
    assert "Associates" in outputs["person-dossier.md"]
    assert "Cited Sources" in outputs["person-dossier.md"]
    assert "example-workshop.pdf" in outputs["person-dossier.md"]
    assert "**profile-child (source " in outputs["person-dossier.md"]
    assert "**record-one (source " in outputs["person-dossier.md"]
    assert "3 tasks require your attention" in outputs["action-queue.md"]


def test_dossier_uses_first_unresolved_research_search_before_paid_action(
    tmp_path: Path,
) -> None:
    """Filtering the headline to user actions can skip the actual next research step."""
    payload = valid_research_payload()
    question = payload["question"]
    assert isinstance(question, dict)
    question["searches"] = [
        {
            "key": "fictional-workshop-search",
            "repository": "Fable Workshop Library",
            "collection": "Probate",
            "target": "Complete workshop material",
            "locator": "Workshop register C:24",
            "url": None,
            "required_action": "none",
            "expected_value": "Compare apprentice ages in the first planned workshop search.",
            "destination_path": None,
            "status": "planned",
            "result_summary": None,
        },
        {
            "key": "paid-harvest",
            "repository": "Example Subscription Archive",
            "collection": "Paid records",
            "target": "Paid harvest",
            "locator": None,
            "url": "https://example.invalid/paid",
            "required_action": "approve_payment",
            "expected_value": "Search paid records after the free sweep.",
            "destination_path": "data/private/paid",
            "status": "planned",
            "result_summary": None,
        },
    ]
    connection = _ingest_payload(tmp_path, payload)

    outputs = render_research_outputs(
        load_research_state(connection, "Who were the example parents?")
    )

    assert (
        "Next decisive evidence: "
        "Compare apprentice ages in the first planned workshop search."
        in outputs["person-dossier.md"]
    )
    assert "paid-harvest" in outputs["action-queue.md"]
    assert "fictional-workshop-search" not in outputs["action-queue.md"]


def test_research_outputs_use_required_stable_ordering(tmp_path: Path) -> None:
    """Sorting batch-ordered sections or leaving queues unstable causes noisy diffs."""
    connection = _ingest_payload(tmp_path, _ordered_payload())
    state = load_research_state(connection, "Who were the example parents?")

    outputs = render_research_outputs(state)

    assert outputs["direct-line-audit.md"].index(
        "FIRST LINE ANCHOR"
    ) < outputs["direct-line-audit.md"].index("SECOND LINE ANCHOR")
    assert outputs["person-dossier.md"].index(
        "FIRST TIMELINE EVENT"
    ) < outputs["person-dossier.md"].index("SECOND TIMELINE EVENT")
    assert outputs["hypothesis-matrix.md"].index(
        "leading-key"
    ) < outputs["hypothesis-matrix.md"].index("later-key")
    assert outputs["action-queue.md"].index(
        "a-paid"
    ) < outputs["action-queue.md"].index(
        "z-paid"
    ) < outputs["action-queue.md"].index("download-first")


def test_hypotheses_use_key_as_stable_tie_breaker(tmp_path: Path) -> None:
    """Equal-rank hypotheses need a deterministic secondary key."""
    connection = _ingest_payload(tmp_path, _ordered_payload())
    state = load_research_state(connection, "Who were the example parents?")
    hypotheses = state["current_conclusion"]["hypotheses"]
    hypotheses[0]["rank"] = 1
    hypotheses[0]["key"] = "z-tie"
    hypotheses[1]["rank"] = 1
    hypotheses[1]["key"] = "a-tie"

    output = render_research_outputs(state)["hypothesis-matrix.md"]

    assert output.index("a-tie") < output.index("z-tie")


def test_research_state_parses_json_and_joins_source_file_metadata(
    tmp_path: Path,
) -> None:
    """Returning raw JSON or omitting source-file links makes the state unusable."""
    connection = _ingest_payload(tmp_path, _ordered_payload())

    state = load_research_state(connection, "Who were the example parents?")

    assert isinstance(state["planned_searches"], list)
    assert isinstance(state["negative_results"], list)
    assert isinstance(state["current_conclusion"], dict)
    assert [
        (source["source_key"], source["record_title"])
        for source in state["sources"]
    ] == [
        ("profile-child", "Example Child profile"),
        ("record-one", "Example workshop register"),
    ]
    assert state["sources"][1]["files"] == [
        {
            "local_path": "data/private/research/example-workshop.pdf",
            "ocr_status": "not_started",
            "original_filename": "example-workshop.pdf",
            "rights_label": "personal_research",
            "sha256": (
                "cca7a072a98601383fc639dd246646ced47b67001e4c23b27d"
                "8e9f86b1e7aeac"
            ),
            "size_bytes": 27,
            "source_file_id": 1,
            "transcription_status": "not_started",
        }
    ]


def test_research_state_uses_latest_row_for_each_stable_source_key(
    tmp_path: Path,
) -> None:
    """Repeating stable keys across immutable batches must not duplicate citations."""
    record = (
        tmp_path
        / "data"
        / "private"
        / "research"
        / "example-workshop.pdf"
    )
    record.parent.mkdir(parents=True)
    record.write_bytes(b"fictional workshop register")
    connection = create_store(tmp_path / "genealogy.sqlite")

    first_payload = valid_research_payload()
    first_batch = load_research_batch(
        _write_batch(tmp_path / "first-batch.json", first_payload)
    )
    ingest_research_batch(connection, first_batch, tmp_path)

    second_payload = json.loads(json.dumps(first_payload))
    second_payload["batch_id"] = "fictional-parentage-v2"
    second_payload["sources"][0]["record_title"] = (
        "Example Child profile, revised citation"
    )
    second_batch = load_research_batch(
        _write_batch(tmp_path / "second-batch.json", second_payload)
    )
    ingest_research_batch(connection, second_batch, tmp_path)

    state = load_research_state(connection, "Who were the example parents?")

    assert [
        (source["source_key"], source["record_title"])
        for source in state["sources"]
    ] == [
        ("profile-child", "Example Child profile, revised citation"),
        ("record-one", "Example workshop register"),
    ]


def test_research_state_json_is_pretty_sorted_and_newline_terminated(
    tmp_path: Path,
) -> None:
    """Compact, key-unstable JSON creates noisy and hard-to-review state files."""
    connection = _ingest_payload(tmp_path, _ordered_payload())
    state = load_research_state(connection, "Who were the example parents?")

    output = render_research_outputs(state)["research-state.json"]

    assert output == json.dumps(
        state,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def test_load_research_state_requires_one_exact_title(tmp_path: Path) -> None:
    """A fuzzy or ambiguous title could silently render the wrong investigation."""
    connection = _ingest_payload(tmp_path, _ordered_payload())

    with pytest.raises(
        ValueError,
        match=r"^research question not found: who were the example parents\?$",
    ):
        load_research_state(connection, "who were the example parents?")

    connection.execute("DROP INDEX ux_research_question_title")
    connection.execute(
        """
        INSERT INTO research_question(
            title, status, target_people_json, target_relationships_json,
            planned_searches, negative_results, current_conclusion
        )
        SELECT title, status, target_people_json, target_relationships_json,
               planned_searches, negative_results, current_conclusion
        FROM research_question
        """
    )
    with pytest.raises(
        ValueError,
        match=r"^multiple research questions match exact title: "
        r"Who were the example parents\?$",
    ):
        load_research_state(connection, "Who were the example parents?")
