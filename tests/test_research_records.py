"""Strict immutable research-batch loader tests."""

import json
from pathlib import Path

import pytest

from genealogy.research_records import (
    ResearchBatchValidationError,
    load_research_batch,
)
from tests.fixtures.research_batch import (
    valid_research_payload,
    write_research_batch_fixture,
)


def _write_payload(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_research_batch_digest_is_order_stable_for_object_keys(
    tmp_path: Path,
) -> None:
    """Changing JSON object order must not alter a batch's canonical digest."""
    first = write_research_batch_fixture(tmp_path / "first.json")
    second_payload = json.loads(first.read_text(encoding="utf-8"))
    second = tmp_path / "second.json"
    second.write_text(json.dumps(second_payload, sort_keys=True), encoding="utf-8")

    assert load_research_batch(first).digest() == load_research_batch(second).digest()


def test_research_batch_rejects_unknown_field(tmp_path: Path) -> None:
    """Ignoring unexpected fields could conceal unsupported research data."""
    payload = valid_research_payload()
    payload["surprise"] = True

    with pytest.raises(ResearchBatchValidationError, match="unknown field"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_duplicate_json_field(tmp_path: Path) -> None:
    """Accepting duplicate object fields would make the source document ambiguous."""
    path = tmp_path / "batch.json"
    path.write_text(
        '{"format_version":1,"format_version":1}', encoding="utf-8"
    )

    with pytest.raises(ResearchBatchValidationError, match="duplicate field"):
        load_research_batch(path)


def test_research_batch_rejects_dangling_source_reference(tmp_path: Path) -> None:
    """An assertion must not point to a source outside its batch."""
    payload = valid_research_payload()
    payload["assertions"][0]["source_key"] = "missing-source"  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="missing-source"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize(
    ("collection", "path"),
    [
        ("people", ("people", 1, "key")),
        ("sources", ("sources", 1, "key")),
        ("assertions", ("assertions", 0, "key")),
        ("relationships", ("relationships", 0, "key")),
        ("searches", ("question", "searches", 0, "key")),
        ("hypotheses", ("question", "hypotheses", 0, "key")),
    ],
)
def test_research_batch_rejects_duplicate_record_keys(
    tmp_path: Path, collection: str, path: tuple[str | int, ...]
) -> None:
    """Duplicate keys would make internal references resolve unpredictably."""
    payload = valid_research_payload()
    value: object = payload
    for part in path:
        value = value[part]  # type: ignore[index]
    if collection == "people":
        value = payload["people"][0]["key"]  # type: ignore[index]
    elif collection == "sources":
        value = payload["sources"][0]["key"]  # type: ignore[index]
    elif collection == "assertions":
        value = "example-child-birth"
        payload["assertions"].append(payload["assertions"][0].copy())  # type: ignore[index]
    elif collection == "relationships":
        payload["relationships"].append(payload["relationships"][0].copy())  # type: ignore[index]
    elif collection == "searches":
        payload["question"]["searches"].append(  # type: ignore[index]
            payload["question"]["searches"][0].copy()  # type: ignore[index]
        )
    else:
        payload["question"]["hypotheses"].append(  # type: ignore[index]
            payload["question"]["hypotheses"][0].copy()  # type: ignore[index]
        )
    if collection in {"people", "sources"}:
        target: list[dict[str, object]] = payload[collection]  # type: ignore[assignment]
        target[1]["key"] = value

    with pytest.raises(ResearchBatchValidationError, match="duplicate key"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_living_person(tmp_path: Path) -> None:
    """Living people are excluded from this non-private research format."""
    payload = valid_research_payload()
    payload["people"][0]["deceased"] = False  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="deceased"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize("field", ["name_confidence", "name_rationale"])
def test_research_batch_requires_name_review_metadata(
    tmp_path: Path,
    field: str,
) -> None:
    """A name cannot become current without explicit review metadata."""
    payload = valid_research_payload()
    del payload["people"][0][field]  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match=field):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_invalid_name_confidence(tmp_path: Path) -> None:
    """An uncontrolled name confidence would bypass the confidence policy."""
    payload = valid_research_payload()
    payload["people"][0]["name_confidence"] = "certain"  # type: ignore[index]

    with pytest.raises(
        ResearchBatchValidationError,
        match="name_confidence.*invalid",
    ):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize("rationale", ["", "   "])
def test_research_batch_rejects_blank_name_rationale(
    tmp_path: Path,
    rationale: str,
) -> None:
    """A blank rationale cannot explain why the current name was selected."""
    payload = valid_research_payload()
    payload["people"][0]["name_rationale"] = rationale  # type: ignore[index]

    with pytest.raises(
        ResearchBatchValidationError,
        match="name_rationale.*nonempty",
    ):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize(
    "unsafe_path",
    ["/records/example.pdf", "records/../example.pdf", "C:outside-project.json"],
)
def test_research_batch_rejects_unsafe_file_path(
    tmp_path: Path, unsafe_path: str
) -> None:
    """Absolute and parent-traversal paths escape the project data boundary."""
    payload = valid_research_payload()
    payload["sources"][1]["file"]["path"] = unsafe_path  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="project-relative"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize("unsafe_path", ["../escape.pdf", "D:outside-project.json"])
def test_research_batch_rejects_unsafe_destination_path(
    tmp_path: Path, unsafe_path: str
) -> None:
    """A planned download destination must stay inside the project."""
    payload = valid_research_payload()
    payload["question"]["searches"][0]["destination_path"] = unsafe_path  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="project-relative"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_invalid_familysearch_id(tmp_path: Path) -> None:
    """Malformed FamilySearch identifiers cannot safely link outside records."""
    payload = valid_research_payload()
    payload["people"][0]["familysearch_id"] = "invalid"  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="FamilySearch ID"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_invalid_status(tmp_path: Path) -> None:
    """Uncontrolled labels make downstream research workflow state ambiguous."""
    payload = valid_research_payload()
    payload["question"]["status"] = "perhaps"  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="status"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("rights_label", "unknown"),
        ("ocr_status", "finished"),
        ("transcription_status", "finished"),
    ),
)
def test_research_batch_rejects_invalid_source_file_controlled_value(
    tmp_path: Path,
    field: str,
    invalid_value: str,
) -> None:
    """Invalid file workflow labels must fail at the strict input boundary."""
    payload = valid_research_payload()
    payload["sources"][1]["file"][field] = invalid_value  # type: ignore[index]

    with pytest.raises(
        ResearchBatchValidationError,
        match=rf"{field}.*invalid",
    ):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_non_string_relationship_role(tmp_path: Path) -> None:
    """A malformed role must be reported as a validation error, never a loader crash."""
    payload = valid_research_payload()
    payload["relationships"][0]["role"] = []  # type: ignore[index]

    with pytest.raises(ResearchBatchValidationError, match="relationship role"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))


def test_research_batch_rejects_missing_hypothesis_evidence_source(
    tmp_path: Path,
) -> None:
    """Hypothesis evidence must cite a source supplied by the same batch."""
    payload = valid_research_payload()
    payload["question"]["hypotheses"][0]["evidence"][0]["source_key"] = (  # type: ignore[index]
        "missing-source"
    )

    with pytest.raises(ResearchBatchValidationError, match="missing-source"):
        load_research_batch(_write_payload(tmp_path / "batch.json", payload))
