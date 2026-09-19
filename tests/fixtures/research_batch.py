"""Shared fictional payload for research-batch loader tests."""

import json
from pathlib import Path


def valid_research_payload() -> dict[str, object]:
    return {
        "format_version": 1,
        "batch_id": "example-parentage-v1",
        "people": [
            {
                "key": "example-child",
                "display_name": "Example Child",
                "name_confidence": "accepted_working",
                "name_rationale": "Coherent example profile name.",
                "deceased": True,
                "familysearch_id": "AAAA-111",
                "source_key": "profile-child",
            },
            {
                "key": "example-parent",
                "display_name": "Example Parent",
                "name_confidence": "plausible_lead",
                "name_rationale": "The workshop register supplies this example name.",
                "deceased": True,
                "familysearch_id": "BBBB-222",
                "source_key": "record-one",
            },
        ],
        "sources": [
            {
                "key": "profile-child",
                "source_type": "online_profile",
                "repository": "Example Archive",
                "collection_name": "Example Profiles",
                "record_title": "Example Child profile",
                "jurisdiction": None,
                "volume": None,
                "page": None,
                "url": "https://example.invalid/child",
                "accessed_at": "2026-07-26",
                "evidence_tier": "tree_aggregate",
                "citation_text": "Example Child profile, accessed 26 Jul 2026.",
                "file": None,
            },
            {
                "key": "record-one",
                "source_type": "workshop_register",
                "repository": "Fable Workshop Library",
                "collection_name": "Example Workshop Registers",
                "record_title": "Example workshop register",
                "jurisdiction": "Larkhaven, Mistvale, Fictional Republic",
                "volume": "C",
                "page": "24",
                "url": "https://example.invalid/record",
                "accessed_at": "2026-07-26",
                "evidence_tier": "original_record",
                "citation_text": "Fable Workshop Register C:24 (invented).",
                "file": {
                    "path": "data/private/research/example-workshop.pdf",
                    "original_filename": "example-workshop.pdf",
                    "rights_label": "personal_research",
                    "ocr_status": "not_started",
                    "transcription_status": "not_started",
                },
            },
        ],
        "assertions": [
            {
                "key": "example-child-birth",
                "person_key": "example-child",
                "source_key": "profile-child",
                "predicate": "event.birth",
                "value_text": "abt 1750",
                "raw_value": "abt 1750",
                "parsed_value": {
                    "modifier": "about",
                    "start": {"year": 1750, "month": None, "day": None},
                    "end": None,
                },
                "confidence": "accepted_working",
                "rationale": "Coherent example profile claim.",
            }
        ],
        "relationships": [
            {
                "key": "example-parent-child",
                "parent_key": "example-parent",
                "child_key": "example-child",
                "role": "father",
                "source_key": "record-one",
                "confidence": "quarantined_contradiction",
                "rationale": "Fixture relationship intentionally requires review.",
            }
        ],
        "question": {
            "title": "Who were the example parents?",
            "status": "in_progress",
            "summary": "The example relationship remains unresolved.",
            "target_person_keys": ["example-child"],
            "line_anchor": [
                {
                    "person_key": "example-child",
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
            "searches": [
                {
                    "key": "example-paid-search",
                    "repository": "Example Archive",
                    "collection": "Example Workshop Registers",
                    "target": "Complete workshop register",
                    "locator": "Volume C, page 24",
                    "url": "https://example.invalid/record",
                    "required_action": "approve_payment",
                    "expected_value": "May distinguish the two apprentices.",
                    "destination_path": "data/private/example-workshop.pdf",
                    "status": "planned",
                    "result_summary": None,
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
    }


def write_research_batch_fixture(path: Path) -> Path:
    path.write_text(
        json.dumps(valid_research_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
