"""Immutable raw records extracted from a RootsMagic snapshot."""

from dataclasses import dataclass
from typing import Literal

from genealogy.rm_dates import ParsedDate


@dataclass(frozen=True, slots=True)
class RawPerson:
    """A RootsMagic person and their primary name."""

    snapshot_id: str
    external_person_id: str
    primary_name_id: str
    primary_name: str
    surname: str
    given: str
    suffix: str
    sex: int
    living: bool
    private: bool
    source_parent_family_id: str | None


@dataclass(frozen=True, slots=True)
class RawIdentifier:
    """An external identifier linked to a RootsMagic person."""

    snapshot_id: str
    external_person_id: str
    system: str
    value: str
    source_link_id: str


@dataclass(frozen=True, slots=True)
class RawRelationship:
    """One relationship edge expanded from a RootsMagic source row."""

    snapshot_id: str
    kind: Literal["parent_child", "spouse"]
    subject_person_id: str
    object_person_id: str
    role: Literal["father", "mother"] | None
    source_family_id: str
    source_child_link_id: str | None


@dataclass(frozen=True, slots=True)
class RawEvent:
    """A RootsMagic event with its explicit date-decoding result."""

    snapshot_id: str
    external_event_id: str
    owner_type: int
    external_owner_id: str
    external_family_id: str | None
    fact_type_id: str
    fact_type_name: str
    raw_date: str
    date: ParsedDate
    external_place_id: str | None
    raw_place_name: str | None
    details: str
    note: str
    private: bool


@dataclass(frozen=True, slots=True)
class RawPlace:
    """A RootsMagic place retaining the imported text unchanged."""

    snapshot_id: str
    external_place_id: str
    place_type: int
    raw_name: str


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    """A deterministic collection of raw records from one source snapshot."""

    snapshot_id: str
    people: tuple[RawPerson, ...]
    identifiers: tuple[RawIdentifier, ...]
    relationships: tuple[RawRelationship, ...]
    events: tuple[RawEvent, ...]
    places: tuple[RawPlace, ...]
    source_family_count: int
    source_child_link_count: int
