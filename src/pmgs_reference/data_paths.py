"""Cross-platform data roots and fail-closed current database pointers."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from pmgs_reference.store_types import JSONDict

CURRENT_POINTER_SCHEMA_VERSION = "1.0"
_RELEASE_ID = re.compile(r"^JPPM[0-9]+$")
_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")


class CurrentPointerError(ValueError):
    """Raised when state/current.json is malformed or escapes its data root."""


@dataclass(frozen=True, slots=True)
class CurrentPointer:
    """Validated metadata and resolved database for one current.json pointer."""

    release_id: str
    source_manifest_sha256: str
    database_sha256: str
    database_schema_version: int
    database_relpath: str
    activated_at: str
    database: Path

    def as_dict(self) -> JSONDict:
        return {
            "schema_version": CURRENT_POINTER_SCHEMA_VERSION,
            "release_id": self.release_id,
            "source_manifest_sha256": self.source_manifest_sha256,
            "database_sha256": self.database_sha256,
            "database_schema_version": self.database_schema_version,
            "database_relpath": self.database_relpath,
            "activated_at": self.activated_at,
        }


@dataclass(frozen=True, slots=True)
class ResolvedDatabase:
    """A resolved database path and the managed pointer that selected it, if any."""

    path: Path
    pointer: CurrentPointer | None


def default_data_root(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the user data root defined by the v0.3 local setup contract."""
    current_platform = platform or sys.platform
    current_environ = environ if environ is not None else os.environ
    current_home = (home or Path.home()).expanduser().absolute()
    if current_platform == "win32":
        local_app_data = current_environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else current_home / "AppData" / "Local"
        return (base / "pmgs-reference").expanduser().absolute()
    if current_platform == "darwin":
        return (current_home / "Library" / "Application Support" / "pmgs-reference").absolute()
    xdg_data_home = current_environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home).expanduser() if xdg_data_home else current_home / ".local" / "share"
    return (base / "pmgs-reference").absolute()


def _required_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise CurrentPointerError(f"current.json has an invalid {name}")
    return value


def _required_match(payload: Mapping[str, object], name: str, pattern: re.Pattern[str]) -> str:
    value = _required_string(payload, name)
    if not pattern.fullmatch(value):
        raise CurrentPointerError(f"current.json has an invalid {name}")
    return value


def _database_from_relpath(data_root: Path, relpath: str) -> Path:
    if "\\" in relpath or ":" in relpath:
        raise CurrentPointerError("current.json database_relpath must be a portable relative path")
    pure = PurePosixPath(relpath)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise CurrentPointerError("current.json database_relpath must stay inside the data root")
    if pure.suffix.lower() != ".sqlite":
        raise CurrentPointerError("current.json database_relpath must identify a SQLite file")
    root = data_root.expanduser().resolve()
    candidate = root.joinpath(*pure.parts).resolve()
    if not candidate.is_relative_to(root):
        raise CurrentPointerError("current.json database_relpath escapes the data root")
    if not candidate.is_file():
        raise CurrentPointerError("current.json points to a missing database")
    return candidate


def read_current_pointer(data_dir: str | os.PathLike[str]) -> CurrentPointer | None:
    """Parse current.json; return None only when it does not exist."""
    root = Path(data_dir).expanduser().resolve()
    path = root / "state" / "current.json"
    if not path.exists():
        return None
    if not path.is_file():
        raise CurrentPointerError("current.json is not a regular file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurrentPointerError(f"current.json cannot be parsed: {type(exc).__name__}") from exc
    if not isinstance(raw, dict):
        raise CurrentPointerError("current.json must contain a JSON object")
    payload = cast(dict[str, object], raw)
    if payload.get("schema_version") != CURRENT_POINTER_SCHEMA_VERSION:
        raise CurrentPointerError("current.json has an unsupported schema_version")
    schema_version = payload.get("database_schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise CurrentPointerError("current.json has an invalid database_schema_version")
    relpath = _required_string(payload, "database_relpath")
    release_id = _required_match(payload, "release_id", _RELEASE_ID)
    source_sha256 = _required_match(payload, "source_manifest_sha256", _SHA256)
    database_sha256 = _required_match(payload, "database_sha256", _SHA256)
    expected_relpath = (
        PurePosixPath("data")
        / "releases"
        / release_id
        / source_sha256
        / f"{database_sha256}.sqlite"
    ).as_posix()
    if relpath != "data/current.sqlite" and relpath != expected_relpath:
        raise CurrentPointerError("current.json database_relpath does not match its identity")
    return CurrentPointer(
        release_id=release_id,
        source_manifest_sha256=source_sha256,
        database_sha256=database_sha256,
        database_schema_version=schema_version,
        database_relpath=relpath,
        activated_at=_required_string(payload, "activated_at"),
        database=_database_from_relpath(root, relpath),
    )


def resolve_database(
    path: str | os.PathLike[str] | None = None,
    *,
    data_dir: str | os.PathLike[str] | None = None,
) -> ResolvedDatabase:
    """Resolve explicit DB, explicit data root, environment DB, then managed default."""
    if path is not None and data_dir is not None:
        raise ValueError("path and data_dir are mutually exclusive")
    if path is not None:
        return ResolvedDatabase(Path(path).expanduser().resolve(), None)
    if data_dir is not None:
        root = Path(data_dir).expanduser().resolve()
        pointer = read_current_pointer(root)
        return ResolvedDatabase(
            pointer.database if pointer is not None else root / "data" / "current.sqlite",
            pointer,
        )
    configured = os.environ.get("PMGS_REFERENCE_DB")
    if configured:
        return ResolvedDatabase(Path(configured).expanduser().resolve(), None)
    root = default_data_root().resolve()
    pointer = read_current_pointer(root)
    return ResolvedDatabase(
        pointer.database if pointer is not None else root / "data" / "current.sqlite",
        pointer,
    )


def resolve_database_path(
    path: str | os.PathLike[str] | None = None,
    *,
    data_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Return only the path from :func:`resolve_database` for compatibility."""
    return resolve_database(path, data_dir=data_dir).path


def write_json_atomic(path: Path, payload: object) -> None:
    """Write one UTF-8 JSON document and replace its destination atomically."""
    destination = path.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}-", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
