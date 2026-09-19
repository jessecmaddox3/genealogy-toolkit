"""Strict immutable records for a self-contained genealogy research batch."""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
from typing import Literal


Confidence = Literal[
    "accepted_working",
    "plausible_lead",
    "quarantined_contradiction",
]
EvidenceTier = Literal[
    "original_record",
    "derivative_record",
    "authored_narrative",
    "family_knowledge",
    "tree_aggregate",
]
SearchStatus = Literal[
    "planned",
    "accessible",
    "blocked",
    "downloaded",
    "processed",
    "no_relevant_result",
    "rejected",
]
RequiredAction = Literal[
    "none",
    "sign_in",
    "download",
    "order",
    "approve_payment",
]
RightsLabel = Literal[
    "public_domain",
    "personal_research",
    "restricted",
    "private_family",
]
OcrStatus = Literal[
    "not_started",
    "raw",
    "corrected",
    "not_applicable",
]
TranscriptionStatus = Literal[
    "not_started",
    "partial",
    "complete",
    "not_applicable",
]


@dataclass(frozen=True, slots=True)
class ResearchFile:
    path: str
    original_filename: str
    rights_label: RightsLabel
    ocr_status: OcrStatus
    transcription_status: TranscriptionStatus


@dataclass(frozen=True, slots=True)
class ResearchPerson:
    key: str
    display_name: str
    name_confidence: Confidence
    name_rationale: str
    deceased: bool
    familysearch_id: str | None
    source_key: str


@dataclass(frozen=True, slots=True)
class ResearchSource:
    key: str
    source_type: str
    repository: str | None
    collection_name: str | None
    record_title: str
    jurisdiction: str | None
    volume: str | None
    page: str | None
    url: str | None
    accessed_at: str | None
    evidence_tier: EvidenceTier
    citation_text: str | None
    file: ResearchFile | None


@dataclass(frozen=True, slots=True)
class ResearchAssertion:
    key: str
    person_key: str
    source_key: str
    predicate: str
    value_text: str | None
    raw_value: str | None
    parsed_value: dict[str, object] | None
    confidence: Confidence
    rationale: str


@dataclass(frozen=True, slots=True)
class ResearchRelationship:
    key: str
    parent_key: str
    child_key: str
    role: Literal["father", "mother"] | None
    source_key: str
    confidence: Confidence
    rationale: str


@dataclass(frozen=True, slots=True)
class ResearchSearch:
    key: str
    repository: str
    collection: str
    target: str
    locator: str | None
    url: str | None
    required_action: RequiredAction
    expected_value: str
    destination_path: str | None
    status: SearchStatus
    result_summary: str | None


@dataclass(frozen=True, slots=True)
class HypothesisEvidence:
    source_key: str
    direction: Literal["supports", "conflicts", "context"]
    weight: Literal["low", "medium", "high"]
    rationale: str


@dataclass(frozen=True, slots=True)
class ResearchHypothesis:
    key: str
    statement: str
    rank: int
    status: Literal["active", "supported", "rejected", "unresolved"]
    evidence: tuple[HypothesisEvidence, ...]


@dataclass(frozen=True, slots=True)
class LineAnchor:
    person_key: str
    basis: str
    confidence: Confidence
    note: str


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    date_text: str
    place_text: str | None
    event_text: str
    source_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssociateEntry:
    name: str
    relationship: str
    source_keys: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class ResearchQuestionInput:
    title: str
    status: Literal["open", "in_progress", "resolved", "paused"]
    summary: str
    target_person_keys: tuple[str, ...]
    line_anchor: tuple[LineAnchor, ...]
    timeline: tuple[TimelineEntry, ...]
    associates: tuple[AssociateEntry, ...]
    searches: tuple[ResearchSearch, ...]
    hypotheses: tuple[ResearchHypothesis, ...]


@dataclass(frozen=True, slots=True)
class ResearchBatch:
    format_version: int
    batch_id: str
    people: tuple[ResearchPerson, ...]
    sources: tuple[ResearchSource, ...]
    assertions: tuple[ResearchAssertion, ...]
    relationships: tuple[ResearchRelationship, ...]
    question: ResearchQuestionInput

    def digest(self) -> str:
        canonical_json = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ResearchBatchValidationError(ValueError):
    """A user-correctable research-batch input error."""


_BATCH_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,79}\Z")
_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,79}\Z")
_FAMILYSEARCH_ID_PATTERN = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{3}\Z")
_CONFIDENCES = frozenset(Confidence.__args__)
_EVIDENCE_TIERS = frozenset(EvidenceTier.__args__)
_SEARCH_STATUSES = frozenset(SearchStatus.__args__)
_REQUIRED_ACTIONS = frozenset(RequiredAction.__args__)
RIGHTS_LABELS = frozenset(RightsLabel.__args__)
OCR_STATUSES = frozenset(OcrStatus.__args__)
TRANSCRIPTION_STATUSES = frozenset(TranscriptionStatus.__args__)


def _object(value: object, fields: set[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ResearchBatchValidationError(f"{context} must be an object")
    unexpected = set(value) - fields
    if unexpected:
        raise ResearchBatchValidationError(
            f"{context} has unknown field {sorted(unexpected)[0]}"
        )
    missing = fields - set(value)
    if missing:
        raise ResearchBatchValidationError(
            f"{context} is missing required field {sorted(missing)[0]}"
        )
    return value


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ResearchBatchValidationError(f"{context} must be an array")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ResearchBatchValidationError(f"{context} must be a string")
    return value


def _nonempty_string(value: object, context: str) -> str:
    text = _string(value, context)
    if not text.strip():
        raise ResearchBatchValidationError(f"{context} must be nonempty")
    return text


def _optional_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context)


def _key(value: object, context: str) -> str:
    key = _string(value, context)
    if not _KEY_PATTERN.fullmatch(key):
        raise ResearchBatchValidationError(f"{context} must be a valid key")
    return key


def _controlled(value: object, choices: frozenset[str], context: str) -> str:
    label = _string(value, context)
    if label not in choices:
        raise ResearchBatchValidationError(f"{context} has invalid value {label}")
    return label


def _project_path(value: object, context: str) -> str:
    path = _string(value, context)
    pieces = path.replace("\\", "/").split("/")
    if (
        not path
        or path.startswith(("/", "\\"))
        or Path(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or PureWindowsPath(path).drive
        or ".." in pieces
    ):
        raise ResearchBatchValidationError(f"{context} must be project-relative")
    return path


def _unique_keys(records: tuple[object, ...], context: str) -> None:
    seen: set[str] = set()
    for record in records:
        key = record.key  # type: ignore[union-attr]
        if key in seen:
            raise ResearchBatchValidationError(f"{context} has duplicate key {key}")
        seen.add(key)


def _check_reference(key: str, available: set[str], context: str) -> None:
    if key not in available:
        raise ResearchBatchValidationError(f"{context} references missing key {key}")


def _load_json(path: Path) -> dict[str, object]:
    def reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ResearchBatchValidationError(f"duplicate field {key}")
            payload[key] = value
        return payload

    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_fields)
    except ResearchBatchValidationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchBatchValidationError(f"cannot read research batch: {error}") from error
    if not isinstance(raw, dict):
        raise ResearchBatchValidationError("research batch must be an object")
    return raw


def load_research_batch(path: Path) -> ResearchBatch:
    """Load one version-1 research batch and validate its closed-world links."""
    payload = _object(
        _load_json(path),
        {"format_version", "batch_id", "people", "sources", "assertions", "relationships", "question"},
        "research batch",
    )
    format_version = payload["format_version"]
    if type(format_version) is not int or format_version != 1:
        raise ResearchBatchValidationError("format_version must equal 1")
    batch_id = _string(payload["batch_id"], "batch_id")
    if not _BATCH_ID_PATTERN.fullmatch(batch_id):
        raise ResearchBatchValidationError("batch_id must be valid")

    sources = tuple(_parse_source(value) for value in _array(payload["sources"], "sources"))
    people = tuple(_parse_person(value) for value in _array(payload["people"], "people"))
    assertions = tuple(
        _parse_assertion(value) for value in _array(payload["assertions"], "assertions")
    )
    relationships = tuple(
        _parse_relationship(value)
        for value in _array(payload["relationships"], "relationships")
    )
    question = _parse_question(payload["question"])

    _unique_keys(people, "people")
    _unique_keys(sources, "sources")
    _unique_keys(assertions, "assertions")
    _unique_keys(relationships, "relationships")
    _unique_keys(question.searches, "searches")
    _unique_keys(question.hypotheses, "hypotheses")
    ranks = [hypothesis.rank for hypothesis in question.hypotheses]
    if len(set(ranks)) != len(ranks):
        raise ResearchBatchValidationError("hypotheses have duplicate rank")

    person_keys = {person.key for person in people}
    source_keys = {source.key for source in sources}
    for person in people:
        _check_reference(person.source_key, source_keys, f"person {person.key}")
    for assertion in assertions:
        _check_reference(assertion.person_key, person_keys, f"assertion {assertion.key}")
        _check_reference(assertion.source_key, source_keys, f"assertion {assertion.key}")
    for relationship in relationships:
        if relationship.parent_key == relationship.child_key:
            raise ResearchBatchValidationError(f"relationship {relationship.key}: a person cannot be their own parent")
        _check_reference(relationship.parent_key, person_keys, f"relationship {relationship.key}")
        _check_reference(relationship.child_key, person_keys, f"relationship {relationship.key}")
        _check_reference(relationship.source_key, source_keys, f"relationship {relationship.key}")
    for key in question.target_person_keys:
        _check_reference(key, person_keys, "question target_person_keys")
    for anchor in question.line_anchor:
        _check_reference(anchor.person_key, person_keys, "line anchor")
    for entry in question.timeline:
        for key in entry.source_keys:
            _check_reference(key, source_keys, "timeline")
    for entry in question.associates:
        for key in entry.source_keys:
            _check_reference(key, source_keys, "associate")
    for hypothesis in question.hypotheses:
        for evidence in hypothesis.evidence:
            _check_reference(evidence.source_key, source_keys, "hypothesis evidence")

    return ResearchBatch(
        format_version=format_version,
        batch_id=batch_id,
        people=people,
        sources=sources,
        assertions=assertions,
        relationships=relationships,
        question=question,
    )


def _parse_file(value: object) -> ResearchFile | None:
    if value is None:
        return None
    payload = _object(
        value,
        {"path", "original_filename", "rights_label", "ocr_status", "transcription_status"},
        "file",
    )
    return ResearchFile(
        path=_project_path(payload["path"], "file path"),
        original_filename=_string(payload["original_filename"], "original_filename"),
        rights_label=_controlled(
            payload["rights_label"],
            RIGHTS_LABELS,
            "rights_label",
        ),  # type: ignore[arg-type]
        ocr_status=_controlled(
            payload["ocr_status"],
            OCR_STATUSES,
            "ocr_status",
        ),  # type: ignore[arg-type]
        transcription_status=_controlled(
            payload["transcription_status"],
            TRANSCRIPTION_STATUSES,
            "transcription_status",
        ),  # type: ignore[arg-type]
    )


def validate_research_file_metadata(file: ResearchFile) -> None:
    """Validate controlled file metadata for programmatic batch callers."""
    controlled_values = (
        ("rights_label", file.rights_label, RIGHTS_LABELS),
        ("ocr_status", file.ocr_status, OCR_STATUSES),
        (
            "transcription_status",
            file.transcription_status,
            TRANSCRIPTION_STATUSES,
        ),
    )
    for context, value, choices in controlled_values:
        if not isinstance(value, str) or value not in choices:
            raise ResearchBatchValidationError(
                f"{context} has invalid value {value}"
            )


def _parse_person(value: object) -> ResearchPerson:
    payload = _object(
        value,
        {
            "key",
            "display_name",
            "name_confidence",
            "name_rationale",
            "deceased",
            "familysearch_id",
            "source_key",
        },
        "person",
    )
    deceased = payload["deceased"]
    if deceased is not True:
        raise ResearchBatchValidationError("person deceased must be true")
    familysearch_id = _optional_string(payload["familysearch_id"], "familysearch_id")
    if familysearch_id is not None and not _FAMILYSEARCH_ID_PATTERN.fullmatch(familysearch_id):
        raise ResearchBatchValidationError("FamilySearch ID must be valid")
    return ResearchPerson(
        key=_key(payload["key"], "person key"),
        display_name=_string(payload["display_name"], "display_name"),
        name_confidence=_controlled(
            payload["name_confidence"],
            _CONFIDENCES,
            "name_confidence",
        ),  # type: ignore[arg-type]
        name_rationale=_nonempty_string(
            payload["name_rationale"],
            "name_rationale",
        ),
        deceased=deceased,
        familysearch_id=familysearch_id,
        source_key=_key(payload["source_key"], "person source_key"),
    )


def _parse_source(value: object) -> ResearchSource:
    payload = _object(value, {"key", "source_type", "repository", "collection_name", "record_title", "jurisdiction", "volume", "page", "url", "accessed_at", "evidence_tier", "citation_text", "file"}, "source")
    return ResearchSource(
        key=_key(payload["key"], "source key"),
        source_type=_string(payload["source_type"], "source_type"),
        repository=_optional_string(payload["repository"], "repository"),
        collection_name=_optional_string(payload["collection_name"], "collection_name"),
        record_title=_string(payload["record_title"], "record_title"),
        jurisdiction=_optional_string(payload["jurisdiction"], "jurisdiction"),
        volume=_optional_string(payload["volume"], "volume"),
        page=_optional_string(payload["page"], "page"),
        url=_optional_string(payload["url"], "url"),
        accessed_at=_optional_string(payload["accessed_at"], "accessed_at"),
        evidence_tier=_controlled(payload["evidence_tier"], _EVIDENCE_TIERS, "evidence_tier"),  # type: ignore[arg-type]
        citation_text=_optional_string(payload["citation_text"], "citation_text"),
        file=_parse_file(payload["file"]),
    )


def _parse_assertion(value: object) -> ResearchAssertion:
    payload = _object(value, {"key", "person_key", "source_key", "predicate", "value_text", "raw_value", "parsed_value", "confidence", "rationale"}, "assertion")
    parsed_value = payload["parsed_value"]
    if parsed_value is not None and not isinstance(parsed_value, dict):
        raise ResearchBatchValidationError("parsed_value must be an object or null")
    return ResearchAssertion(
        key=_key(payload["key"], "assertion key"),
        person_key=_key(payload["person_key"], "assertion person_key"),
        source_key=_key(payload["source_key"], "assertion source_key"),
        predicate=_string(payload["predicate"], "predicate"),
        value_text=_optional_string(payload["value_text"], "value_text"),
        raw_value=_optional_string(payload["raw_value"], "raw_value"),
        parsed_value=parsed_value,
        confidence=_controlled(payload["confidence"], _CONFIDENCES, "confidence"),  # type: ignore[arg-type]
        rationale=_string(payload["rationale"], "rationale"),
    )


def _parse_relationship(value: object) -> ResearchRelationship:
    payload = _object(value, {"key", "parent_key", "child_key", "role", "source_key", "confidence", "rationale"}, "relationship")
    role = payload["role"]
    if role is not None and role not in ("father", "mother"):
        raise ResearchBatchValidationError("relationship role must be father, mother, or null")
    return ResearchRelationship(
        key=_key(payload["key"], "relationship key"),
        parent_key=_key(payload["parent_key"], "relationship parent_key"),
        child_key=_key(payload["child_key"], "relationship child_key"),
        role=role,
        source_key=_key(payload["source_key"], "relationship source_key"),
        confidence=_controlled(payload["confidence"], _CONFIDENCES, "confidence"),  # type: ignore[arg-type]
        rationale=_string(payload["rationale"], "rationale"),
    )


def _parse_question(value: object) -> ResearchQuestionInput:
    payload = _object(value, {"title", "status", "summary", "target_person_keys", "line_anchor", "timeline", "associates", "searches", "hypotheses"}, "question")
    target_person_keys = tuple(_key(key, "target_person_key") for key in _array(payload["target_person_keys"], "target_person_keys"))
    if not target_person_keys:
        raise ResearchBatchValidationError("question target_person_keys cannot be empty")
    hypotheses = tuple(_parse_hypothesis(item) for item in _array(payload["hypotheses"], "hypotheses"))
    return ResearchQuestionInput(
        title=_string(payload["title"], "question title"),
        status=_controlled(payload["status"], frozenset({"open", "in_progress", "resolved", "paused"}), "question status"),  # type: ignore[arg-type]
        summary=_string(payload["summary"], "question summary"),
        target_person_keys=target_person_keys,
        line_anchor=tuple(_parse_line_anchor(item) for item in _array(payload["line_anchor"], "line_anchor")),
        timeline=tuple(_parse_timeline(item) for item in _array(payload["timeline"], "timeline")),
        associates=tuple(_parse_associate(item) for item in _array(payload["associates"], "associates")),
        searches=tuple(_parse_search(item) for item in _array(payload["searches"], "searches")),
        hypotheses=hypotheses,
    )


def _parse_line_anchor(value: object) -> LineAnchor:
    payload = _object(value, {"person_key", "basis", "confidence", "note"}, "line anchor")
    return LineAnchor(
        person_key=_key(payload["person_key"], "line anchor person_key"),
        basis=_string(payload["basis"], "line anchor basis"),
        confidence=_controlled(payload["confidence"], _CONFIDENCES, "line anchor confidence"),  # type: ignore[arg-type]
        note=_string(payload["note"], "line anchor note"),
    )


def _parse_timeline(value: object) -> TimelineEntry:
    payload = _object(value, {"date_text", "place_text", "event_text", "source_keys"}, "timeline")
    return TimelineEntry(
        date_text=_string(payload["date_text"], "timeline date_text"),
        place_text=_optional_string(payload["place_text"], "timeline place_text"),
        event_text=_string(payload["event_text"], "timeline event_text"),
        source_keys=tuple(_key(key, "timeline source_key") for key in _array(payload["source_keys"], "timeline source_keys")),
    )


def _parse_associate(value: object) -> AssociateEntry:
    payload = _object(value, {"name", "relationship", "source_keys", "note"}, "associate")
    return AssociateEntry(
        name=_string(payload["name"], "associate name"),
        relationship=_string(payload["relationship"], "associate relationship"),
        source_keys=tuple(_key(key, "associate source_key") for key in _array(payload["source_keys"], "associate source_keys")),
        note=_string(payload["note"], "associate note"),
    )


def _parse_search(value: object) -> ResearchSearch:
    payload = _object(value, {"key", "repository", "collection", "target", "locator", "url", "required_action", "expected_value", "destination_path", "status", "result_summary"}, "search")
    destination_path = payload["destination_path"]
    return ResearchSearch(
        key=_key(payload["key"], "search key"),
        repository=_string(payload["repository"], "search repository"),
        collection=_string(payload["collection"], "search collection"),
        target=_string(payload["target"], "search target"),
        locator=_optional_string(payload["locator"], "search locator"),
        url=_optional_string(payload["url"], "search url"),
        required_action=_controlled(payload["required_action"], _REQUIRED_ACTIONS, "required_action"),  # type: ignore[arg-type]
        expected_value=_string(payload["expected_value"], "search expected_value"),
        destination_path=None if destination_path is None else _project_path(destination_path, "destination_path"),
        status=_controlled(payload["status"], _SEARCH_STATUSES, "search status"),  # type: ignore[arg-type]
        result_summary=_optional_string(payload["result_summary"], "search result_summary"),
    )


def _parse_hypothesis(value: object) -> ResearchHypothesis:
    payload = _object(value, {"key", "statement", "rank", "status", "evidence"}, "hypothesis")
    rank = payload["rank"]
    if type(rank) is not int or rank <= 0:
        raise ResearchBatchValidationError("hypothesis rank must be a positive integer")
    return ResearchHypothesis(
        key=_key(payload["key"], "hypothesis key"),
        statement=_string(payload["statement"], "hypothesis statement"),
        rank=rank,
        status=_controlled(payload["status"], frozenset({"active", "supported", "rejected", "unresolved"}), "hypothesis status"),  # type: ignore[arg-type]
        evidence=tuple(_parse_hypothesis_evidence(item) for item in _array(payload["evidence"], "hypothesis evidence")),
    )


def _parse_hypothesis_evidence(value: object) -> HypothesisEvidence:
    payload = _object(value, {"source_key", "direction", "weight", "rationale"}, "hypothesis evidence")
    direction = _controlled(payload["direction"], frozenset({"supports", "conflicts", "context"}), "evidence direction")
    weight = _controlled(payload["weight"], frozenset({"low", "medium", "high"}), "evidence weight")
    return HypothesisEvidence(
        source_key=_key(payload["source_key"], "evidence source_key"),
        direction=direction,  # type: ignore[arg-type]
        weight=weight,  # type: ignore[arg-type]
        rationale=_string(payload["rationale"], "evidence rationale"),
    )
