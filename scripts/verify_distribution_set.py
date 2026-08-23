"""Verify that a release artifact directory contains one exact wheel and sdist."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise RuntimeError("pyproject.toml does not declare a project version")
    return cast(str, project["version"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _metadata_fields(payload: bytes) -> dict[str, str | None]:
    message = BytesParser(policy=default).parsebytes(payload)
    return {
        "name": message.get("Name"),
        "version": message.get("Version"),
        "requires_python": message.get("Requires-Python"),
    }


def _wheel_metadata(path: Path) -> dict[str, str | None]:
    with zipfile.ZipFile(path) as archive:
        matches = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(matches) != 1:
            raise RuntimeError("wheel METADATA member is missing or ambiguous")
        return _metadata_fields(archive.read(matches[0]))


def _sdist_metadata(path: Path) -> dict[str, str | None]:
    with tarfile.open(path, "r:gz") as archive:
        matches = [member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")]
        if len(matches) != 1:
            raise RuntimeError("sdist PKG-INFO member is missing or ambiguous")
        source = archive.extractfile(matches[0])
        if source is None:
            raise RuntimeError("sdist PKG-INFO member is unreadable")
        with source:
            return _metadata_fields(source.read())


def verify_distribution_set(dist_dir: Path, version: str) -> dict[str, object]:
    root = dist_dir.resolve()
    if not root.is_dir():
        raise RuntimeError("distribution directory does not exist")
    entries = sorted(root.iterdir(), key=lambda path: path.name)
    symbolic_links = [path.name for path in entries if path.is_symlink()]
    if symbolic_links:
        raise RuntimeError(f"symbolic link distribution entry: {', '.join(symbolic_links)}")
    uv_marker = root / ".gitignore"
    if uv_marker.exists() and not uv_marker.is_file():
        raise RuntimeError("non-file uv build marker: .gitignore")
    entries = [path for path in entries if path.name != ".gitignore"]
    expected_names = {
        f"pmgs_reference-{version}-py3-none-any.whl",
        f"pmgs_reference-{version}.tar.gz",
    }
    actual_names = {path.name for path in entries if path.is_file()}
    non_files = [path.name for path in entries if not path.is_file()]
    unexpected = sorted(actual_names - expected_names)
    missing = sorted(expected_names - actual_names)
    if non_files or unexpected or missing or len(entries) != 2:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected distribution artifact: {', '.join(unexpected)}")
        if non_files:
            details.append(f"non-file distribution entry: {', '.join(non_files)}")
        raise RuntimeError("; ".join(details) or "unexpected distribution artifact set")
    files = sorted(expected_names)
    wheel = root / f"pmgs_reference-{version}-py3-none-any.whl"
    sdist = root / f"pmgs_reference-{version}.tar.gz"
    expected_metadata = {
        "name": "pmgs-reference",
        "version": version,
        "requires_python": ">=3.12",
    }
    if _wheel_metadata(wheel) != expected_metadata:
        raise RuntimeError("wheel metadata does not match the release contract")
    if _sdist_metadata(sdist) != expected_metadata:
        raise RuntimeError("sdist metadata does not match the release contract")
    return {
        "schema_version": "1.0",
        "version": version,
        "files": files,
        "sha256": {name: _sha256(root / name) for name in files},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_distribution_set(args.dist_dir, _project_version())
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
