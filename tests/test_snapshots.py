import json
from pathlib import Path

from genealogy.snapshots import build_manifest, sha256_file, write_manifest


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    sample = tmp_path / "sample.rmtree"
    sample.write_bytes(b"rootsmagic-snapshot")
    assert sha256_file(sample) == "b60519421a7c665fb828bac5e7344f6b8df4c34d2934ce6f854d7bde9c5ca919"


def test_manifest_sorts_relative_paths(tmp_path: Path) -> None:
    second = tmp_path / "b.ged"
    first = tmp_path / "a.rmtree"
    second.write_bytes(b"b")
    first.write_bytes(b"a")
    manifest = build_manifest([second, first], tmp_path)
    assert [item["path"] for item in manifest["files"]] == ["a.rmtree", "b.ged"]
    assert manifest["files"][0]["size"] == 1


def test_write_manifest_is_sorted_and_newline_terminated(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.json"
    manifest = {"files": [], "manifest_version": 1}

    write_manifest(manifest, output)

    assert output.read_text(encoding="utf-8") == json.dumps(
        manifest, indent=2, sort_keys=True
    ) + "\n"
