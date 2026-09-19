"""Minimal, representative RootsMagic SQLite fixture for reader tests."""

import sqlite3
from pathlib import Path


MINIMAL_RM_SCHEMA = """
CREATE TABLE PersonTable (
    PersonID INTEGER PRIMARY KEY,
    Sex INTEGER NOT NULL,
    Living INTEGER NOT NULL,
    IsPrivate INTEGER NOT NULL,
    ParentID INTEGER NOT NULL,
    Note TEXT NOT NULL
);
CREATE TABLE NameTable (
    NameID INTEGER PRIMARY KEY,
    OwnerID INTEGER NOT NULL,
    Surname TEXT NOT NULL,
    Given TEXT NOT NULL,
    Prefix TEXT NOT NULL,
    Suffix TEXT NOT NULL,
    Nickname TEXT NOT NULL,
    NameType INTEGER NOT NULL,
    Date TEXT NOT NULL,
    SortDate INTEGER NOT NULL,
    IsPrimary INTEGER NOT NULL,
    IsPrivate INTEGER NOT NULL,
    Proof INTEGER NOT NULL,
    Sentence TEXT NOT NULL,
    Note TEXT NOT NULL,
    BirthYear INTEGER NOT NULL,
    DeathYear INTEGER NOT NULL,
    Display TEXT NOT NULL,
    Language TEXT NOT NULL,
    UTCModDate REAL NOT NULL,
    SurnameMP TEXT NOT NULL,
    GivenMP TEXT NOT NULL,
    NicknameMP TEXT NOT NULL
);
CREATE TABLE FamilyTable (
    FamilyID INTEGER PRIMARY KEY,
    FatherID INTEGER NOT NULL,
    MotherID INTEGER NOT NULL,
    ChildID INTEGER NOT NULL,
    HusbOrder INTEGER NOT NULL,
    WifeOrder INTEGER NOT NULL,
    IsPrivate INTEGER NOT NULL,
    Proof INTEGER NOT NULL,
    SpouseLabel INTEGER NOT NULL,
    FatherLabel INTEGER NOT NULL,
    MotherLabel INTEGER NOT NULL,
    SpouseLabelStr TEXT NOT NULL,
    FatherLabelStr TEXT NOT NULL,
    MotherLabelStr TEXT NOT NULL,
    Note TEXT NOT NULL,
    UTCModDate REAL NOT NULL
);
CREATE TABLE ChildTable (
    RecID INTEGER PRIMARY KEY,
    ChildID INTEGER NOT NULL,
    FamilyID INTEGER NOT NULL,
    RelFather INTEGER NOT NULL,
    RelMother INTEGER NOT NULL,
    ChildOrder INTEGER NOT NULL,
    IsPrivate INTEGER NOT NULL,
    ProofFather INTEGER NOT NULL,
    ProofMother INTEGER NOT NULL,
    Note TEXT NOT NULL,
    UTCModDate REAL NOT NULL
);
CREATE TABLE EventTable (
    EventID INTEGER PRIMARY KEY,
    EventType INTEGER NOT NULL,
    OwnerType INTEGER NOT NULL,
    OwnerID INTEGER NOT NULL,
    FamilyID INTEGER NOT NULL,
    PlaceID INTEGER NOT NULL,
    Date TEXT NOT NULL,
    SortDate INTEGER NOT NULL,
    IsPrimary INTEGER NOT NULL,
    IsPrivate INTEGER NOT NULL,
    Proof INTEGER NOT NULL,
    Status INTEGER NOT NULL,
    Sentence TEXT NOT NULL,
    Details TEXT NOT NULL,
    Note TEXT NOT NULL,
    UTCModDate REAL NOT NULL
);
CREATE TABLE FactTypeTable (
    FactTypeID INTEGER PRIMARY KEY,
    OwnerType INTEGER NOT NULL,
    Name TEXT NOT NULL,
    Abbrev TEXT NOT NULL,
    GedcomTag TEXT NOT NULL,
    UseValue INTEGER NOT NULL,
    UseDate INTEGER NOT NULL,
    UsePlace INTEGER NOT NULL,
    Sentence TEXT NOT NULL,
    Flags INTEGER NOT NULL,
    UTCModDate REAL NOT NULL
);
CREATE TABLE PlaceTable (
    PlaceID INTEGER PRIMARY KEY,
    PlaceType INTEGER NOT NULL,
    Name TEXT NOT NULL,
    Abbrev TEXT NOT NULL,
    Normalized TEXT NOT NULL,
    Latitude TEXT NOT NULL,
    Longitude TEXT NOT NULL,
    LatLongExact INTEGER NOT NULL,
    MasterID INTEGER NOT NULL,
    Note TEXT NOT NULL,
    Reverse INTEGER NOT NULL,
    fsID TEXT NOT NULL,
    anID TEXT NOT NULL,
    UTCModDate REAL NOT NULL
);
CREATE TABLE FamilySearchTable (
    LinkID INTEGER PRIMARY KEY,
    LinkType INTEGER NOT NULL,
    rmID INTEGER NOT NULL,
    fsID TEXT NOT NULL,
    Modified INTEGER NOT NULL,
    fsVersion TEXT NOT NULL,
    fsDate TEXT NOT NULL,
    Status INTEGER NOT NULL,
    UTCModDate REAL NOT NULL,
    TreeID INTEGER NOT NULL
);
"""


def build_rm_fixture(
    path: Path, *, include_alternate_parent_family: bool = False
) -> Path:
    """Create a small RootsMagic-shaped database at *path*."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(MINIMAL_RM_SCHEMA)
        connection.executemany(
            "INSERT INTO PersonTable(PersonID, Sex, Living, IsPrivate, ParentID, Note) VALUES (?, ?, ?, ?, ?, ?)",
            [(1, 0, 0, 0, 0, ""), (2, 1, 0, 0, 0, ""), (3, 0, 1, 1, 1, "")],
        )
        connection.executemany(
            "INSERT INTO NameTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 1, "Example", "Parent One", "", "", "", 0, ".", 0, 1, 0, 0, "", "", 0, 0, "", "", 0, "", "", ""),
                (2, 2, "Example", "Parent Two", "", "Jr.", "", 0, ".", 0, 1, 0, 0, "", "", 0, 0, "", "", 0, "", "", ""),
                (3, 3, "Example", "Child", "", "", "", 0, ".", 0, 1, 1, 0, "", "", 0, 0, "", "", 0, "", "", ""),
                (4, 3, "Changed", "Alternate", "", "", "", 0, ".", 0, 0, 0, 0, "", "", 0, 0, "", "", 0, "", "", ""),
            ],
        )
        connection.execute(
            "INSERT INTO FamilyTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, "", "", "", "", 0),
        )
        connection.execute(
            "INSERT INTO ChildTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 3, 1, 0, 0, 0, 0, 0, 0, "", 0),
        )
        if include_alternate_parent_family:
            connection.execute(
                "INSERT INTO FamilyTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, "", "", "", "", 0),
            )
            connection.execute(
                "INSERT INTO ChildTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (2, 3, 2, 0, 0, 0, 0, 0, 0, "", 0),
            )
            connection.execute(
                "UPDATE PersonTable SET ParentID = 2 WHERE PersonID = 3"
            )
        connection.executemany(
            "INSERT INTO EventTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 1, 0, 1, 0, 1, "D.+19000102..+00000000..", 19000102, 1, 0, 0, 0, "", "Imported detail", "Imported note", 0),
                (2, 1, 0, 2, 0, 1, "D.+19010203..+00000000..", 19010203, 1, 0, 0, 0, "", "", "", 0),
                (3, 1, 0, 3, 0, 0, "D.+19200405..+00000000..", 19200405, 1, 1, 0, 0, "", "", "", 0),
            ],
        )
        connection.execute(
            "INSERT INTO FactTypeTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 0, "Birth", "Birth", "BIRT", 0, 1, 1, "", 0, 0),
        )
        connection.execute(
            "INSERT INTO PlaceTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 0, "Larkhaven, Mistvale, Fictional Republic", "", "", "", "", 0, 0, "", 0, "", "", 0),
        )
        connection.executemany(
            "INSERT INTO FamilySearchTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(1, 0, 1, "AAAA-111", 0, "", "", 0, 0, 0), (2, 0, 2, "BBBB-222", 0, "", "", 0, 0, 0), (3, 0, 3, "CCCC-333", 0, "", "", 0, 0, 0)],
        )
        connection.commit()
    finally:
        connection.close()
    return path
