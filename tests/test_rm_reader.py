import importlib
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from tests.fixtures.rm_fixture import build_rm_fixture


def _reader() -> ModuleType:
    try:
        return importlib.import_module("genealogy.rm_reader")
    except ModuleNotFoundError:
        pytest.fail("genealogy.rm_reader is required for RootsMagic imports")


def test_rootsmagic_connection_is_read_only(tmp_path: Path) -> None:
    """The returned connection must reject DELETE statements."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")

    connection = _reader().open_rootsmagic(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM PersonTable")
    finally:
        connection.close()


def test_schema_guard_names_missing_table(tmp_path: Path) -> None:
    """Removing FamilySearchTable must prevent incomplete data extraction."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE FamilySearchTable")
        connection.commit()
    finally:
        connection.close()

    reader = _reader()
    with pytest.raises(reader.RootsMagicSchemaError, match="FamilySearchTable"):
        reader.open_rootsmagic(path)


def test_schema_guard_names_missing_column(tmp_path: Path) -> None:
    """Removing PersonTable.Living must prevent a partial person import."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")
    connection = sqlite3.connect(path)
    try:
        connection.execute("ALTER TABLE PersonTable DROP COLUMN Living")
        connection.commit()
    finally:
        connection.close()

    reader = _reader()
    with pytest.raises(reader.RootsMagicSchemaError, match=r"PersonTable\.Living"):
        reader.open_rootsmagic(path)


def test_rootsmagic_connection_registers_rm_nocase_collation(tmp_path: Path) -> None:
    """Without RMNOCASE registration, RootsMagic-style comparisons fail."""
    path = build_rm_fixture(tmp_path / "fixture.rmtree")

    connection = _reader().open_rootsmagic(path)
    try:
        result = connection.execute(
            "SELECT 'Álpha' = 'álpha' COLLATE RMNOCASE"
        ).fetchone()[0]
    finally:
        connection.close()

    assert result == 1
