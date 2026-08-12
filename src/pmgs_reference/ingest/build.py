"""Atomic construction of the versioned PMGS SQLite store."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from pmgs_reference.data_paths import write_json_atomic
from pmgs_reference.ingest.adapters import process_sources
from pmgs_reference.ingest.database import DatabaseWriter
from pmgs_reference.ingest.inventory import SourceInventory, build_inventory
from pmgs_reference.schema import SCHEMA_VERSION
from pmgs_reference.validation import logical_digest

_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WINDOWS = os.name == "nt"
_REFERENCE_DATE_GROUPS = frozenset(
    {
        "FI/FI",
        "FI/FI_TEXT",
        "FI/FI_TEXT_E",
        "FTERM/THEME",
        "FTERM/THEME_E",
        "FTERM/FTERM",
        "FTERM/FTERM_E",
        "IPC/IPC4_TEXT",
        "IPC/IPC5_TEXT",
        "IPC/IPC6_TEXT",
        "IPC/IPC7_TEXT",
        "IPC/IPC7E_TEXT",
        "IPC/IPC8B_TEXT",
        "IPC/IPC8U_TEXT",
    }
)
_COUNTED_TABLES = (
    "release",
    "source_file",
    "source_record",
    "release_source",
    "concept",
    "concept_revision",
    "concept_text",
    "concept_property",
    "relation",
    "revision_relation",
    "document",
    "document_text",
    "document_link",
    "document_revision_link",
    "reference_entry",
    "build_issue",
)


class BuildError(RuntimeError):
    """Raised when a candidate database fails its construction gates."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    schema_version: str
    release_id: str
    reference_date: str
    source_manifest_sha256: str
    source_file_count: int
    source_total_bytes: int
    database_file: str
    database_size_bytes: int
    database_sha256: str
    logical_digest: str
    table_counts: dict[str, int]
    warning_count: int
    error_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _reference_date(inventory: SourceInventory) -> str:
    values: set[dt.date] = set()
    for entry in inventory.entries:
        if entry.file_type != "csv" or entry.data_group not in _REFERENCE_DATE_GROUPS:
            continue
        match = re.search(r"_([0-9]{8})\.csv$", entry.relative_path, re.IGNORECASE)
        if match is None:
            # Some registered PMGS packages contain isolated malformed filenames.
            # The release date is selected only from exact, parseable filename dates;
            # all such dates must still agree, so no value is inferred from a typo.
            continue
        try:
            values.add(dt.datetime.strptime(match.group(1), "%Y%m%d").date())
        except ValueError as exc:
            raise BuildError("recognized classification CSV has an invalid YYYYMMDD date") from exc
    if len(values) != 1:
        raise BuildError(
            "source package must contain exactly one valid classification CSV reference date"
        )
    return next(iter(values)).isoformat()


def _same_inventory(left: SourceInventory, right: SourceInventory) -> bool:
    return (
        left.logical_sha256 == right.logical_sha256
        and left.total_bytes == right.total_bytes
        and left.entries == right.entries
    )


def _count_tables(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _COUNTED_TABLES:
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        assert row is not None
        counts[table] = int(row[0])
    return counts


def _retry_permission_error(operation: Callable[[], None], *, attempts: int) -> None:
    delay = 0.05
    for attempt in range(attempts):
        try:
            operation()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 0.5)


def promote_database_exclusive(
    temporary_path: Path, output_path: Path, *, permission_attempts: int = 1
) -> None:
    """Promote a complete database without replacing an existing destination."""
    if permission_attempts < 1:
        raise ValueError("permission_attempts must be positive")
    try:
        os.link(temporary_path, output_path)
    except FileExistsError:
        raise FileExistsError(f"database output already exists: {output_path}") from None
    except OSError:
        if not _WINDOWS:
            raise
        try:
            # Windows rename is atomic within one volume and never replaces an
            # existing destination. This is the safe fallback for FAT/exFAT,
            # which do not support hard links. POSIX rename may overwrite, so
            # non-Windows platforms fail closed above.
            _retry_permission_error(
                lambda: os.rename(temporary_path, output_path), attempts=permission_attempts
            )
        except FileExistsError:
            raise FileExistsError(f"database output already exists: {output_path}") from None
    else:
        _retry_permission_error(temporary_path.unlink, attempts=permission_attempts)


def build_database(
    source_root: Path,
    release_id: str,
    output_path: Path,
    report_path: Path | None = None,
    *,
    inventory: SourceInventory | None = None,
    progress: Callable[[str], None] | None = None,
) -> BuildResult:
    """Build and atomically install a canonical database from one PMGS package."""
    if not _RELEASE_ID.fullmatch(release_id):
        raise ValueError("release_id must be 1-64 URL-safe characters")
    source_root = source_root.expanduser().absolute()
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"database output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}-", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    if progress is not None:
        progress("inventory")
    source_inventory = build_inventory(source_root)
    if inventory is not None and not _same_inventory(source_inventory, inventory):
        temporary_path.unlink(missing_ok=True)
        raise BuildError(
            "supplied source inventory does not match the immediate pre-build snapshot"
        )
    failures = [entry for entry in source_inventory.entries if entry.status == "failed"]
    if failures:
        temporary_path.unlink(missing_ok=True)
        raise BuildError(f"source inventory contains {len(failures)} failed file(s)")
    reference_date = _reference_date(source_inventory)

    if progress is not None:
        progress("database")
    connection = sqlite3.connect(temporary_path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA foreign_keys = ON")
        writer = DatabaseWriter(connection, release_id, reference_date, source_inventory)
        writer.initialize()
        process_sources(writer, source_root, source_inventory.entries)
        connection.commit()

        post_inventory = build_inventory(source_root)
        if not _same_inventory(source_inventory, post_inventory):
            raise BuildError("source package changed during database construction")

        foreign_key_errors = list(connection.execute("PRAGMA foreign_key_check"))
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing"
        warning_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM build_issue WHERE severity = 'warning'"
            ).fetchone()[0]
        )
        error_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM build_issue WHERE severity = 'error'"
            ).fetchone()[0]
        )
        if integrity != "ok" or foreign_key_errors or error_count:
            raise BuildError(
                "candidate database failed gates: "
                f"integrity={integrity}, foreign_keys={len(foreign_key_errors)}, "
                f"build_errors={error_count}"
            )
        table_counts = _count_tables(connection)
        database_logical_digest = logical_digest(connection)
        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.execute("VACUUM")
    except Exception as exc:
        connection.close()
        if temporary_path.exists():
            temporary_path.unlink()
        if isinstance(exc, BuildError):
            raise
        raise BuildError(f"source processing failed: {type(exc).__name__}") from exc
    else:
        connection.close()

    database_sha256 = _sha256_file(temporary_path)
    database_size_bytes = temporary_path.stat().st_size
    try:
        promote_database_exclusive(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    result = BuildResult(
        schema_version=SCHEMA_VERSION,
        release_id=release_id,
        reference_date=reference_date,
        source_manifest_sha256=source_inventory.logical_sha256,
        source_file_count=len(source_inventory.entries),
        source_total_bytes=source_inventory.total_bytes,
        database_file=output_path.name,
        database_size_bytes=database_size_bytes,
        database_sha256=database_sha256,
        logical_digest=database_logical_digest,
        table_counts=table_counts,
        warning_count=warning_count,
        error_count=error_count,
    )
    if report_path is not None:
        write_json_atomic(report_path.resolve(), result.as_dict())
    if progress is not None:
        progress("complete")
    return result
