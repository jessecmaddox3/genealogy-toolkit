"""Deterministic manifests for immutable acquisition snapshots."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(paths: Sequence[Path], root: Path) -> dict[str, object]:
    """Build a deterministic manifest for files below *root*."""
    files = [
        {
            "path": path.resolve().relative_to(root.resolve()).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(paths, key=lambda item: item.as_posix())
    ]
    return {"manifest_version": 1, "files": files}


def write_manifest(manifest: Mapping[str, object], output: Path) -> None:
    """Write *manifest* as stable, human-readable JSON."""
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
