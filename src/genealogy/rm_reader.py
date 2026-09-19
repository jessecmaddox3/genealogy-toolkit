"""Read-only access and schema validation for RootsMagic SQLite snapshots."""

import sqlite3
from pathlib import Path

from genealogy.records import (
    RawEvent,
    RawIdentifier,
    RawPerson,
    RawPlace,
    RawRelationship,
    RawSnapshot,
)
from genealogy.rm_dates import parse_rm_date


REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "PersonTable": frozenset(
        {"PersonID", "Sex", "Living", "IsPrivate", "ParentID", "Note"}
    ),
    "NameTable": frozenset(
        {
            "NameID",
            "OwnerID",
            "Surname",
            "Given",
            "Prefix",
            "Suffix",
            "Nickname",
            "NameType",
            "Date",
            "SortDate",
            "IsPrimary",
            "IsPrivate",
            "Proof",
            "Sentence",
            "Note",
            "BirthYear",
            "DeathYear",
            "Display",
            "Language",
            "UTCModDate",
            "SurnameMP",
            "GivenMP",
            "NicknameMP",
        }
    ),
    "FamilyTable": frozenset(
        {
            "FamilyID",
            "FatherID",
            "MotherID",
            "ChildID",
            "HusbOrder",
            "WifeOrder",
            "IsPrivate",
            "Proof",
            "SpouseLabel",
            "FatherLabel",
            "MotherLabel",
            "SpouseLabelStr",
            "FatherLabelStr",
            "MotherLabelStr",
            "Note",
            "UTCModDate",
        }
    ),
    "ChildTable": frozenset(
        {
            "RecID",
            "ChildID",
            "FamilyID",
            "RelFather",
            "RelMother",
            "ChildOrder",
            "IsPrivate",
            "ProofFather",
            "ProofMother",
            "Note",
            "UTCModDate",
        }
    ),
    "EventTable": frozenset(
        {
            "EventID",
            "EventType",
            "OwnerType",
            "OwnerID",
            "FamilyID",
            "PlaceID",
            "Date",
            "SortDate",
            "IsPrimary",
            "IsPrivate",
            "Proof",
            "Status",
            "Sentence",
            "Details",
            "Note",
            "UTCModDate",
        }
    ),
    "FactTypeTable": frozenset(
        {
            "FactTypeID",
            "OwnerType",
            "Name",
            "Abbrev",
            "GedcomTag",
            "UseValue",
            "UseDate",
            "UsePlace",
            "Sentence",
            "Flags",
            "UTCModDate",
        }
    ),
    "PlaceTable": frozenset(
        {
            "PlaceID",
            "PlaceType",
            "Name",
            "Abbrev",
            "Normalized",
            "Latitude",
            "Longitude",
            "LatLongExact",
            "MasterID",
            "Note",
            "Reverse",
            "fsID",
            "anID",
            "UTCModDate",
        }
    ),
    "FamilySearchTable": frozenset(
        {
            "LinkID",
            "LinkType",
            "rmID",
            "fsID",
            "Modified",
            "fsVersion",
            "fsDate",
            "Status",
            "UTCModDate",
            "TreeID",
        }
    ),
}


class RootsMagicSchemaError(RuntimeError):
    """Raised when a RootsMagic snapshot lacks required tables or columns."""


class RootsMagicExtractionError(RuntimeError):
    """Raised when source rows cannot be extracted without data loss."""


def _rm_nocase(left: str | None, right: str | None) -> int:
    """Provide RootsMagic's case-insensitive collation for SQLite queries."""
    normalized_left = (left or "").casefold()
    normalized_right = (right or "").casefold()
    return (normalized_left > normalized_right) - (normalized_left < normalized_right)


def validate_schema(connection: sqlite3.Connection) -> None:
    """Raise a detailed error unless *connection* exposes the expected schema."""
    table_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing_items: list[str] = []

    for table_name in sorted(REQUIRED_COLUMNS):
        if table_name not in table_names:
            missing_items.append(f"table {table_name}")
            continue

        column_names = {
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{table_name}")'
            )
        }
        missing_items.extend(
            f"column {table_name}.{column_name}"
            for column_name in sorted(REQUIRED_COLUMNS[table_name] - column_names)
        )

    if missing_items:
        raise RootsMagicSchemaError(
            "RootsMagic schema is missing required " + ", ".join(missing_items)
        )


def open_rootsmagic(path: Path) -> sqlite3.Connection:
    """Open and validate a RootsMagic database without permitting writes."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.create_collation("RMNOCASE", _rm_nocase)
    try:
        validate_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _external_id(value: int) -> str:
    return str(value)


def _optional_external_id(value: int) -> str | None:
    return None if value == 0 else str(value)


def _extract_people(
    connection: sqlite3.Connection, snapshot_id: str
) -> tuple[RawPerson, ...]:
    rows = connection.execute(
        """
        SELECT
            person.PersonID,
            name.NameID,
            name.Surname,
            name.Given,
            name.Suffix,
            person.Sex,
            person.Living,
            person.IsPrivate,
            person.ParentID
        FROM PersonTable AS person
        JOIN NameTable AS name
          ON name.OwnerID = person.PersonID
         AND name.IsPrimary = 1
        ORDER BY person.PersonID, name.NameID
        """
    )
    people = tuple(
        RawPerson(
            snapshot_id=snapshot_id,
            external_person_id=_external_id(row["PersonID"]),
            primary_name_id=_external_id(row["NameID"]),
            primary_name=" ".join(
                part
                for part in (row["Given"], row["Surname"], row["Suffix"])
                if part
            ),
            surname=row["Surname"],
            given=row["Given"],
            suffix=row["Suffix"],
            sex=row["Sex"],
            living=bool(row["Living"]),
            private=bool(row["IsPrivate"]),
            source_parent_family_id=_optional_external_id(row["ParentID"]),
        )
        for row in rows
    )
    source_count = connection.execute(
        "SELECT count(*) FROM PersonTable"
    ).fetchone()[0]
    if len(people) != source_count:
        raise RootsMagicExtractionError(
            "Primary-name extraction returned "
            f"{len(people)} records for {source_count} people"
        )
    return people


def _extract_identifiers(
    connection: sqlite3.Connection, snapshot_id: str
) -> tuple[RawIdentifier, ...]:
    rows = connection.execute(
        """
        SELECT LinkID, rmID, fsID
        FROM FamilySearchTable
        WHERE LinkType = 0 AND fsID != ''
        ORDER BY LinkID
        """
    )
    return tuple(
        RawIdentifier(
            snapshot_id=snapshot_id,
            external_person_id=_external_id(row["rmID"]),
            system="familysearch",
            value=row["fsID"],
            source_link_id=_external_id(row["LinkID"]),
        )
        for row in rows
    )


def _extract_relationships(
    connection: sqlite3.Connection, snapshot_id: str
) -> tuple[RawRelationship, ...]:
    relationships: list[RawRelationship] = []
    child_rows = connection.execute(
        """
        SELECT
            child_link.RecID,
            child_link.ChildID,
            child_link.FamilyID,
            child.PersonID AS ResolvedChildID,
            family.FamilyID AS ResolvedFamilyID,
            family.FatherID,
            family.MotherID
        FROM ChildTable AS child_link
        LEFT JOIN PersonTable AS child
          ON child.PersonID = child_link.ChildID
        LEFT JOIN FamilyTable AS family
          ON family.FamilyID = child_link.FamilyID
        ORDER BY child_link.RecID
        """
    )
    for row in child_rows:
        if row["ResolvedChildID"] is None:
            raise RootsMagicExtractionError(
                f"ChildTable.RecID={row['RecID']} references missing "
                f"PersonTable.PersonID={row['ChildID']}"
            )
        if row["ResolvedFamilyID"] is None:
            raise RootsMagicExtractionError(
                f"ChildTable.RecID={row['RecID']} references missing "
                f"FamilyTable.FamilyID={row['FamilyID']}"
            )
        family_id = _external_id(row["FamilyID"])
        child_link_id = _external_id(row["RecID"])
        child_id = _external_id(row["ChildID"])
        if row["FatherID"] != 0:
            relationships.append(
                RawRelationship(
                    snapshot_id,
                    "parent_child",
                    _external_id(row["FatherID"]),
                    child_id,
                    "father",
                    family_id,
                    child_link_id,
                )
            )
        if row["MotherID"] != 0:
            relationships.append(
                RawRelationship(
                    snapshot_id,
                    "parent_child",
                    _external_id(row["MotherID"]),
                    child_id,
                    "mother",
                    family_id,
                    child_link_id,
                )
            )

    family_rows = connection.execute(
        """
        SELECT FamilyID, FatherID, MotherID
        FROM FamilyTable
        WHERE FatherID != 0 AND MotherID != 0
        ORDER BY FamilyID
        """
    )
    relationships.extend(
        RawRelationship(
            snapshot_id,
            "spouse",
            _external_id(row["FatherID"]),
            _external_id(row["MotherID"]),
            None,
            _external_id(row["FamilyID"]),
            None,
        )
        for row in family_rows
    )
    return tuple(relationships)


def _extract_events(
    connection: sqlite3.Connection, snapshot_id: str
) -> tuple[RawEvent, ...]:
    rows = connection.execute(
        """
        SELECT
            event.EventID,
            event.OwnerType,
            event.OwnerID,
            event.FamilyID,
            event.EventType,
            fact_type.Name AS FactTypeName,
            event.Date,
            event.PlaceID,
            place.Name AS PlaceName,
            event.Details,
            event.Note,
            event.IsPrivate
        FROM EventTable AS event
        JOIN FactTypeTable AS fact_type
          ON fact_type.FactTypeID = event.EventType
         AND fact_type.OwnerType = event.OwnerType
        LEFT JOIN PlaceTable AS place
          ON place.PlaceID = event.PlaceID
        ORDER BY event.EventID
        """
    )
    events = tuple(
        RawEvent(
            snapshot_id=snapshot_id,
            external_event_id=_external_id(row["EventID"]),
            owner_type=row["OwnerType"],
            external_owner_id=_external_id(row["OwnerID"]),
            external_family_id=_optional_external_id(row["FamilyID"]),
            fact_type_id=_external_id(row["EventType"]),
            fact_type_name=row["FactTypeName"],
            raw_date=row["Date"],
            date=parse_rm_date(row["Date"]),
            external_place_id=_optional_external_id(row["PlaceID"]),
            raw_place_name=row["PlaceName"],
            details=row["Details"],
            note=row["Note"],
            private=bool(row["IsPrivate"]),
        )
        for row in rows
    )
    source_count = connection.execute(
        "SELECT count(*) FROM EventTable"
    ).fetchone()[0]
    if len(events) != source_count:
        raise RootsMagicExtractionError(
            "Fact-type extraction returned "
            f"{len(events)} records for {source_count} events"
        )
    return events


def _extract_places(
    connection: sqlite3.Connection, snapshot_id: str
) -> tuple[RawPlace, ...]:
    rows = connection.execute(
        """
        SELECT PlaceID, PlaceType, Name
        FROM PlaceTable
        ORDER BY PlaceID
        """
    )
    return tuple(
        RawPlace(
            snapshot_id=snapshot_id,
            external_place_id=_external_id(row["PlaceID"]),
            place_type=row["PlaceType"],
            raw_name=row["Name"],
        )
        for row in rows
    )


def extract_snapshot(path: Path, snapshot_id: str) -> RawSnapshot:
    """Extract traceable raw records without modifying or normalizing source data."""
    connection = open_rootsmagic(path)
    try:
        people = _extract_people(connection, snapshot_id)
        identifiers = _extract_identifiers(connection, snapshot_id)
        relationships = _extract_relationships(connection, snapshot_id)
        events = _extract_events(connection, snapshot_id)
        places = _extract_places(connection, snapshot_id)
        source_family_count = connection.execute(
            "SELECT count(*) FROM FamilyTable"
        ).fetchone()[0]
        source_child_link_count = connection.execute(
            "SELECT count(*) FROM ChildTable"
        ).fetchone()[0]
    finally:
        connection.close()

    return RawSnapshot(
        snapshot_id=snapshot_id,
        people=people,
        identifiers=identifiers,
        relationships=relationships,
        events=events,
        places=places,
        source_family_count=source_family_count,
        source_child_link_count=source_child_link_count,
    )
