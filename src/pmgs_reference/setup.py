"""Transactional local setup for managed PMGS Reference databases."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Literal, cast

from pmgs_reference.agent_kit import AgentClient
from pmgs_reference.client_integration import (
    ClientTarget,
    CommandRunner,
    integrate_clients,
)
from pmgs_reference.data_paths import (
    CurrentPointer,
    CurrentPointerError,
    read_current_pointer,
    write_json_atomic,
)
from pmgs_reference.diagnostics import DoctorResult, doctor_database
from pmgs_reference.ingest.build import BuildResult, build_database
from pmgs_reference.ingest.inventory import SourceInventory, build_inventory, write_inventory
from pmgs_reference.store import PMGSStore
from pmgs_reference.store_types import JSONDict, JSONValue
from pmgs_reference.validation import ValidationResult, validate_database, write_validation_report

SetupStatus = Literal["ready", "already_ready", "dry_run", "partial_failed", "failed"]
ReleaseIdSource = Literal["explicit", "directory_name", "single_child"]
ProgressCallback = Callable[[str], None]

_SETUP_RELEASE_ID = re.compile(r"^JPPM[0-9]+$")
_SHA256 = re.compile(r"^[A-F0-9]{64}$")


class SetupUsageError(ValueError):
    """Raised for a setup request that cannot be interpreted safely."""


class SetupOperationError(RuntimeError):
    """Raised for an operational gate that prevents activation."""


@dataclass(frozen=True, slots=True)
class SetupResult:
    """One machine-readable local setup outcome."""

    status: SetupStatus
    run_id: str
    release_id: str
    release_id_source: ReleaseIdSource
    source_directory: str
    data_dir: str
    database: str | None
    source_manifest_sha256: str
    database_sha256: str | None
    database_schema_version: int | None
    database_reused: bool
    current_pointer: str | None
    inventory: JSONDict
    clients: tuple[JSONDict, ...]
    cleaned_staging: tuple[str, ...]
    report_directory: str | None
    restart_required: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> JSONDict:
        return {
            "schema_version": "1.0",
            "status": self.status,
            "run_id": self.run_id,
            "release_id": self.release_id,
            "release_id_source": self.release_id_source,
            "source_directory": self.source_directory,
            "data_dir": self.data_dir,
            "database": self.database,
            "source_manifest_sha256": self.source_manifest_sha256,
            "database_sha256": self.database_sha256,
            "database_schema_version": self.database_schema_version,
            "database_reused": self.database_reused,
            "current_pointer": self.current_pointer,
            "inventory": self.inventory,
            "clients": [cast(JSONValue, item) for item in self.clients],
            "cleaned_staging": list(self.cleaned_staging),
            "report_directory": self.report_directory,
            "restart_required": self.restart_required,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


class SetupLock:
    """A non-waiting cross-platform advisory lock released on process exit."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        self._stream: BinaryIO | None = None

    def __enter__(self) -> SetupLock:
        if _is_link_or_junction(self.path.parent) or _is_reparse_point(self.path.parent):
            raise OSError("setup lock parent must not be a link or reparse point")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if _is_link_or_junction(self.path) or _is_reparse_point(self.path):
            raise OSError("setup lock must not be a link or reparse point")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        stream = os.fdopen(descriptor, "r+b")
        try:
            opened = os.fstat(stream.fileno())
            listed = os.stat(self.path, follow_symlinks=False)
        except OSError:
            stream.close()
            raise
        if (opened.st_dev, opened.st_ino) != (listed.st_dev, listed.st_ino):
            stream.close()
            raise OSError("setup lock path changed while it was being opened")
        if opened.st_nlink != 1:
            stream.close()
            raise OSError("setup lock must not be a hard-linked file")
        if self.path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    stream.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
        except OSError as exc:
            stream.close()
            raise OSError("another pmgs setup is already running for this data directory") from exc
        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps(
                {"schema_version": "1.0", "run_id": self.run_id, "pid": os.getpid()},
                sort_keys=True,
            ).encode("utf-8")
        )
        stream.flush()
        os.fsync(stream.fileno())
        self._stream = stream
        return self

    def __exit__(self, *_: object) -> None:
        if self._stream is None:
            return
        stream = self._stream
        file_number = stream.fileno()
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(file_number, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(file_number, fcntl.LOCK_UN)  # type: ignore[attr-defined]
        finally:
            stream.close()
            self._stream = None


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _is_reparse_point(path: Path) -> bool:
    """Return whether an existing Windows path is any kind of reparse point."""
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def _reject_managed_links(data_root: Path) -> None:
    """Reject write-side links and reparse points inside the managed data root."""
    if data_root.exists() and not data_root.is_dir():
        raise SetupUsageError("PMGS data directory must be a directory")
    if _is_link_or_junction(data_root) or _is_reparse_point(data_root):
        raise SetupUsageError("PMGS data directory must not be a link or reparse point")
    if not data_root.exists():
        return
    for root, directories, files in os.walk(data_root, followlinks=False):
        root_path = Path(root)
        for name in [*directories, *files]:
            candidate = root_path / name
            if _is_link_or_junction(candidate) or _is_reparse_point(candidate):
                relative = candidate.relative_to(data_root)
                raise SetupUsageError(
                    f"PMGS data directory contains a link or reparse point: {relative}"
                )


def _reject_source_links(source: Path) -> None:
    if _is_link_or_junction(source):
        raise SetupUsageError("PMGS source directory must not be a symlink or junction")
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        for name in [*directories, *files]:
            candidate = root_path / name
            if _is_link_or_junction(candidate):
                raise SetupUsageError(
                    f"PMGS source contains a symlink or junction: {candidate.relative_to(source)}"
                )


def resolve_setup_source(
    source: str | os.PathLike[str], release_id: str | None
) -> tuple[Path, str, ReleaseIdSource]:
    """Resolve an exact package root or one unambiguous direct JPPM child."""
    requested = release_id.strip() if release_id is not None else None
    if requested is not None and not _SETUP_RELEASE_ID.fullmatch(requested):
        raise SetupUsageError("release must match JPPM followed by digits")
    supplied = Path(source).expanduser().absolute()
    if not supplied.is_dir():
        raise SetupUsageError(f"PMGS source directory not found: {supplied}")
    named_release = supplied.name if _SETUP_RELEASE_ID.fullmatch(supplied.name) else None
    children = sorted(
        (
            child
            for child in supplied.iterdir()
            if child.is_dir() and _SETUP_RELEASE_ID.fullmatch(child.name)
        ),
        key=lambda child: child.name,
    )
    if requested is not None:
        if named_release is not None and named_release != requested:
            raise SetupUsageError(
                f"explicit release {requested} does not match source directory {named_release}"
            )
        if named_release is not None:
            candidate = supplied
        else:
            matching_children = [child for child in children if child.name == requested]
            if matching_children:
                candidate = matching_children[0]
            elif children:
                raise SetupUsageError(
                    f"explicit release {requested} does not match a direct PMGS package directory"
                )
            else:
                candidate = supplied
        origin: ReleaseIdSource = "explicit"
        resolved_release = requested
    elif named_release is not None:
        candidate = supplied
        origin = "directory_name"
        resolved_release = named_release
    elif len(children) == 1:
        candidate = children[0]
        origin = "single_child"
        resolved_release = candidate.name
    elif len(children) > 1:
        raise SetupUsageError("source contains multiple PMGS release directories; pass --release")
    else:
        raise SetupUsageError("release cannot be inferred; pass --release JPPMnnnnnnn")
    _reject_source_links(candidate)
    return candidate.resolve(), resolved_release, origin


def _run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _emit(callback: ProgressCallback | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def _database_identity(path: Path) -> tuple[ValidationResult, str, str]:
    validation = validate_database(path)
    if not validation.valid:
        raise SetupOperationError(f"database validation failed: {path.name}")
    release = PMGSStore.open(path).release_info()
    return (
        validation,
        str(release["release_id"]),
        str(release["source_manifest_sha256"]),
    )


def _verify_current_pointer(pointer: CurrentPointer) -> ValidationResult:
    validation, release_id, source_sha256 = _database_identity(pointer.database)
    if (
        pointer.release_id != release_id
        or pointer.source_manifest_sha256 != source_sha256
        or pointer.database_sha256.upper() != validation.database_sha256
        or pointer.database_schema_version != validation.user_version
    ):
        raise CurrentPointerError("current.json metadata does not match its database")
    return validation


def _clean_stale_staging(
    staging_root: Path,
    active_database: Path | None,
) -> tuple[list[str], list[str]]:
    cleaned: list[str] = []
    warnings: list[str] = []
    if not staging_root.exists():
        return cleaned, warnings
    root = staging_root.resolve()
    for candidate in sorted(staging_root.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or _is_link_or_junction(candidate):
            warnings.append(f"unrecognized staging entry retained: {candidate.name}")
            continue
        resolved = candidate.resolve()
        marker = candidate / "owner.json"
        try:
            owner = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            warnings.append(f"unowned staging directory retained: {candidate.name}")
            continue
        if (
            not resolved.is_relative_to(root)
            or not isinstance(owner, dict)
            or owner.get("schema_version") != "1.0"
            or owner.get("run_id") != candidate.name
            or (active_database is not None and active_database.is_relative_to(resolved))
        ):
            warnings.append(f"untrusted staging directory retained: {candidate.name}")
            continue
        shutil.rmtree(resolved)
        cleaned.append(resolved.relative_to(staging_root.parent).as_posix())
    return cleaned, warnings


def _find_versioned_database(
    data_root: Path,
    release_id: str,
    source_sha256: str,
    warnings: list[str],
    *,
    known_database: tuple[Path, ValidationResult] | None = None,
) -> tuple[Path | None, ValidationResult | None]:
    directory = data_root / "data" / "releases" / release_id / source_sha256
    if not directory.exists():
        return None, None
    valid: list[tuple[Path, ValidationResult]] = []
    for candidate in sorted(directory.glob("*.sqlite"), key=lambda path: path.name):
        if not _SHA256.fullmatch(candidate.stem):
            warnings.append(f"unrecognized database retained: {candidate.name}")
            continue
        resolved_candidate = candidate.resolve()
        if known_database is not None and resolved_candidate == known_database[0]:
            valid.append(known_database)
            continue
        try:
            validation, actual_release, actual_source = _database_identity(candidate)
        except (OSError, ValueError, SetupOperationError, sqlite3.Error):
            warnings.append(f"invalid database retained: {candidate.name}")
            continue
        if (
            actual_release != release_id
            or actual_source != source_sha256
            or validation.database_sha256 != candidate.stem
        ):
            warnings.append(f"database identity mismatch retained: {candidate.name}")
            continue
        valid.append((resolved_candidate, validation))
    hashes = {validation.database_sha256 for _, validation in valid}
    if len(hashes) > 1:
        raise SetupOperationError(
            "determinism check failed: multiple valid database hashes exist for one source manifest"
        )
    return valid[0] if valid else (None, None)


def _client_preview(
    targets: Sequence[ClientTarget], approved_clients: Sequence[AgentClient]
) -> tuple[JSONDict, ...]:
    approved = frozenset(approved_clients)
    return tuple(
        {
            "client": target.client,
            "executable": str(target.executable) if target.executable is not None else None,
            "status": (
                "not_detected"
                if target.executable is None
                else "planned_registration"
                if target.client in approved
                else "declined"
            ),
            "mcp": "not_checked",
            "skill": "not_checked",
            "restart_required": False,
            "error": None,
        }
        for target in targets
    )


def _write_doctor_report(result: DoctorResult, path: Path) -> None:
    write_json_atomic(path, result.as_dict())


def _rename_database(source: Path, destination: Path) -> None:
    """Wait briefly for Windows MCP process handles, then rename on the same filesystem."""
    delay = 0.05
    for attempt in range(20):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 0.5)


def setup_reference(
    source: str | os.PathLike[str],
    *,
    release_id: str | None = None,
    data_dir: str | os.PathLike[str],
    client_targets: Sequence[ClientTarget],
    approved_clients: Sequence[AgentClient],
    dry_run: bool = False,
    progress: ProgressCallback | None = None,
    home: str | Path | None = None,
    command_runner: CommandRunner | None = None,
) -> SetupResult:
    """Build, verify, activate, and optionally register one local PMGS release."""
    _emit(progress, "preflight")
    source_root, resolved_release, release_origin = resolve_setup_source(source, release_id)
    supplied_data_root = Path(data_dir).expanduser().absolute()
    _reject_managed_links(supplied_data_root)
    data_root = supplied_data_root.resolve()
    if source_root.is_relative_to(data_root) or data_root.is_relative_to(source_root):
        raise SetupUsageError("PMGS source and data directory must not contain one another")
    run_id = _run_id()
    pointer_path = data_root / "state" / "current.json"
    current_pointer = read_current_pointer(data_root)
    if dry_run and current_pointer is not None:
        _verify_current_pointer(current_pointer)

    _emit(progress, "inventory")
    inventory = build_inventory(source_root)
    inventory_summary = cast(JSONDict, inventory.summary())
    inventory_failures = [entry for entry in inventory.entries if entry.status == "failed"]
    if dry_run:
        dry_errors = (
            (f"source inventory contains {len(inventory_failures)} failed file(s)",)
            if inventory_failures
            else ()
        )
        return SetupResult(
            status="failed" if dry_errors else "dry_run",
            run_id=run_id,
            release_id=resolved_release,
            release_id_source=release_origin,
            source_directory=str(source_root),
            data_dir=str(data_root),
            database=None,
            source_manifest_sha256=inventory.logical_sha256,
            database_sha256=None,
            database_schema_version=None,
            database_reused=False,
            current_pointer=str(pointer_path) if current_pointer is not None else None,
            inventory=inventory_summary,
            clients=_client_preview(client_targets, approved_clients),
            cleaned_staging=(),
            report_directory=None,
            restart_required=False,
            errors=dry_errors,
            warnings=(),
        )
    if inventory_failures:
        raise SetupOperationError(
            f"source inventory contains {len(inventory_failures)} failed file(s)"
        )

    report_dir: Path | None = None
    run_staging: Path | None = None
    installed_new: Path | None = None
    activated = False
    cleaned_staging: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    selected_database: Path | None = None
    selected_validation: ValidationResult | None = None
    database_reused = False
    client_statuses: tuple[JSONDict, ...] = ()
    try:
        with SetupLock(data_root / "setup.lock", run_id):
            _reject_managed_links(data_root)
            current_pointer = read_current_pointer(data_root)
            current_validation: ValidationResult | None = None
            if current_pointer is not None:
                current_validation = _verify_current_pointer(current_pointer)
            staging_root = data_root / "staging"
            active_database = current_pointer.database if current_pointer is not None else None
            cleaned, cleanup_warnings = _clean_stale_staging(staging_root, active_database)
            cleaned_staging.extend(cleaned)
            warnings.extend(cleanup_warnings)
            report_dir = data_root / "reports" / run_id
            report_dir.mkdir(parents=True, exist_ok=False)
            write_inventory(
                inventory,
                report_dir / "source-manifest.jsonl",
                report_dir / "inventory-summary.json",
            )

            _emit(progress, "reuse")
            versioned_database, versioned_validation = _find_versioned_database(
                data_root,
                resolved_release,
                inventory.logical_sha256,
                warnings,
                known_database=(
                    (current_pointer.database, current_validation)
                    if current_pointer is not None and current_validation is not None
                    else None
                ),
            )
            if current_pointer is not None:
                assert current_validation is not None
                current_release = current_pointer.release_id
                current_source = current_pointer.source_manifest_sha256
                if (
                    current_release == resolved_release
                    and current_source == inventory.logical_sha256
                ):
                    selected_database = current_pointer.database
                    selected_validation = current_validation
                    database_reused = True
            else:
                legacy = data_root / "data" / "current.sqlite"
                if legacy.is_file():
                    try:
                        legacy_validation, legacy_release, legacy_source = _database_identity(
                            legacy
                        )
                    except (OSError, ValueError, SetupOperationError, sqlite3.Error):
                        warnings.append("legacy current.sqlite is invalid and was retained")
                    else:
                        if (
                            legacy_release == resolved_release
                            and legacy_source == inventory.logical_sha256
                        ):
                            selected_database = legacy.resolve()
                            selected_validation = legacy_validation
                            database_reused = True
                        else:
                            warnings.append(
                                "legacy current.sqlite belongs to a different source "
                                "and was retained"
                            )
            if selected_database is None and versioned_database is not None:
                selected_database = versioned_database
                selected_validation = versioned_validation
                database_reused = True

            if selected_database is None:
                _emit(progress, "build")
                run_staging = staging_root / run_id
                run_staging.mkdir(parents=True, exist_ok=False)
                write_json_atomic(
                    run_staging / "owner.json",
                    {"schema_version": "1.0", "run_id": run_id, "pid": os.getpid()},
                )
                candidate = run_staging / "candidate.sqlite"
                build_result: BuildResult = build_database(
                    source_root,
                    resolved_release,
                    candidate,
                    report_path=report_dir / "build-report.json",
                    inventory=inventory,
                    progress=lambda stage: _emit(progress, f"build_{stage}"),
                )
                _emit(progress, "source_check")
                after_inventory: SourceInventory = build_inventory(source_root)
                write_json_atomic(
                    report_dir / "inventory-after-summary.json", after_inventory.summary()
                )
                if after_inventory.logical_sha256 != inventory.logical_sha256:
                    raise SetupOperationError("PMGS source changed during setup")
                _emit(progress, "validate")
                selected_validation = validate_database(candidate)
                write_validation_report(selected_validation, report_dir / "validation-report.json")
                if not selected_validation.valid:
                    raise SetupOperationError("candidate database validation failed")
                if selected_validation.database_sha256 != build_result.database_sha256:
                    raise SetupOperationError("candidate database hash changed after build")
                selected_database = candidate
            else:
                _emit(progress, "source_check")
                after_inventory = build_inventory(source_root)
                write_json_atomic(
                    report_dir / "inventory-after-summary.json", after_inventory.summary()
                )
                if after_inventory.logical_sha256 != inventory.logical_sha256:
                    raise SetupOperationError("PMGS source changed during setup")
                assert selected_validation is not None
                write_validation_report(selected_validation, report_dir / "validation-report.json")

            assert selected_database is not None
            assert selected_validation is not None
            _emit(progress, "doctor")
            doctor = doctor_database(selected_database, python_executable=Path(sys.executable))
            _write_doctor_report(doctor, report_dir / "doctor-report.json")
            if not doctor.ok:
                raise SetupOperationError("candidate database failed the stdio MCP diagnostic")

            if not database_reused:
                _reject_managed_links(data_root)
                destination = (
                    data_root
                    / "data"
                    / "releases"
                    / resolved_release
                    / inventory.logical_sha256
                    / f"{selected_validation.database_sha256}.sqlite"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    existing_validation, existing_release, existing_source = _database_identity(
                        destination
                    )
                    if (
                        existing_validation.database_sha256 != selected_validation.database_sha256
                        or existing_release != resolved_release
                        or existing_source != inventory.logical_sha256
                    ):
                        raise SetupOperationError("immutable database destination is in conflict")
                    selected_database.unlink()
                    selected_database = destination.resolve()
                    selected_validation = existing_validation
                    database_reused = True
                else:
                    _rename_database(selected_database, destination)
                    selected_database = destination.resolve()
                    installed_new = selected_database

            _emit(progress, "activate")
            _reject_managed_links(data_root)
            relpath = selected_database.relative_to(data_root).as_posix()
            pointer_payload: JSONDict = {
                "schema_version": "1.0",
                "release_id": resolved_release,
                "source_manifest_sha256": inventory.logical_sha256,
                "database_sha256": selected_validation.database_sha256,
                "database_schema_version": selected_validation.user_version,
                "database_relpath": relpath,
                "activated_at": datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            pointer_matches = (
                current_pointer is not None
                and current_pointer.database == selected_database
                and current_pointer.release_id == resolved_release
                and current_pointer.source_manifest_sha256 == inventory.logical_sha256
                and current_pointer.database_sha256 == selected_validation.database_sha256
                and current_pointer.database_schema_version == selected_validation.user_version
            )
            pointer_changed = not pointer_matches
            if pointer_changed:
                write_json_atomic(pointer_path, pointer_payload)
            activated = True
            if run_staging is not None and run_staging.exists():
                shutil.rmtree(run_staging)

            _emit(progress, "clients")
            client_statuses = tuple(
                integrate_clients(
                    client_targets,
                    approved_clients,
                    python_executable=Path(sys.executable),
                    data_dir=data_root,
                    home=home,
                    runner=command_runner,
                )
            )
            partial = any(
                item.get("client") in approved_clients
                and item.get("status") in {"not_detected", "conflict", "failed"}
                for item in client_statuses
            )
            status: SetupStatus
            if partial:
                status = "partial_failed"
            elif database_reused:
                status = "already_ready"
            else:
                status = "ready"
            result = SetupResult(
                status=status,
                run_id=run_id,
                release_id=resolved_release,
                release_id_source=release_origin,
                source_directory=str(source_root),
                data_dir=str(data_root),
                database=str(selected_database),
                source_manifest_sha256=inventory.logical_sha256,
                database_sha256=selected_validation.database_sha256,
                database_schema_version=selected_validation.user_version,
                database_reused=database_reused,
                current_pointer=str(pointer_path),
                inventory=inventory_summary,
                clients=client_statuses,
                cleaned_staging=tuple(cleaned_staging),
                report_directory=str(report_dir),
                restart_required=(
                    any(item.get("restart_required") is True for item in client_statuses)
                    or (
                        pointer_changed
                        and any(
                            item.get("status") in {"installed", "already_present"}
                            for item in client_statuses
                        )
                    )
                ),
                errors=(),
                warnings=tuple(warnings),
            )
            write_json_atomic(report_dir / "setup-report.json", result.as_dict())
            _emit(progress, "complete")
            return result
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        if run_staging is not None and run_staging.exists():
            shutil.rmtree(run_staging)
        if installed_new is not None and installed_new.exists() and not activated:
            installed_new.unlink()
        result = SetupResult(
            status="failed",
            run_id=run_id,
            release_id=resolved_release,
            release_id_source=release_origin,
            source_directory=str(source_root),
            data_dir=str(data_root),
            database=(
                str(selected_database) if activated and selected_database is not None else None
            ),
            source_manifest_sha256=inventory.logical_sha256,
            database_sha256=(
                selected_validation.database_sha256
                if activated and selected_validation is not None
                else None
            ),
            database_schema_version=(
                selected_validation.user_version
                if activated and selected_validation is not None
                else None
            ),
            database_reused=database_reused,
            current_pointer=str(pointer_path) if activated else None,
            inventory=inventory_summary,
            clients=client_statuses,
            cleaned_staging=tuple(cleaned_staging),
            report_directory=str(report_dir) if report_dir is not None else None,
            restart_required=False,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        if report_dir is not None:
            with suppress(OSError):
                write_json_atomic(report_dir / "setup-report.json", result.as_dict())
        return result
