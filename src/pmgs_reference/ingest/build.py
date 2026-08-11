"""Atomic construction of the versioned PMGS SQLite store."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from pmgs_reference.data_paths import write_json_atomic
from pmgs_reference.ingest.adapters import process_sources
from pmgs_reference.ingest.database import DatabaseWriter
from pmgs_reference.ingest.inventory import SourceInventory, build_inventory

_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_COUNTED_TABLES = (
    "release",
    "source_file",
    "source_record",
    "concept",
    "concept_text",
    "concept_property",
    "relation",
    "document",
    "document_text",
    "document_link",
    "reference_entry",
    "build_issue",
)


class BuildError(RuntimeError):
    """Raised when a candidate database fails its construction gates."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    schema_version: str
    release_id: str
    source_manifest_sha256: str
    source_file_count: int
    source_total_bytes: int
    database_file: str
    database_size_bytes: int
    database_sha256: str
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


def _count_tables(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _COUNTED_TABLES:
        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        assert row is not None
        counts[table] = int(row[0])
    return counts


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
    source_root = source_root.resolve()
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
    source_inventory = inventory if inventory is not None else build_inventory(source_root)
    failures = [entry for entry in source_inventory.entries if entry.status == "failed"]
    if failures:
        temporary_path.unlink(missing_ok=True)
        raise BuildError(f"source inventory contains {len(failures)} failed file(s)")

    if progress is not None:
        progress("database")
    connection = sqlite3.connect(temporary_path)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA foreign_keys = ON")
        writer = DatabaseWriter(connection, release_id, source_inventory)
        writer.initialize()
        process_sources(writer, source_root, source_inventory.entries)
        connection.commit()

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
        connection.execute("ANALYZE")
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.execute("VACUUM")
    except Exception:
        connection.close()
        if temporary_path.exists():
            temporary_path.unlink()
        raise
    else:
        connection.close()

    database_sha256 = _sha256_file(temporary_path)
    database_size_bytes = temporary_path.stat().st_size
    try:
        os.link(temporary_path, output_path)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        raise FileExistsError(f"database output already exists: {output_path}") from None
    else:
        temporary_path.unlink()
    result = BuildResult(
        schema_version="1.0",
        release_id=release_id,
        source_manifest_sha256=source_inventory.logical_sha256,
        source_file_count=len(source_inventory.entries),
        source_total_bytes=source_inventory.total_bytes,
        database_file=output_path.name,
        database_size_bytes=database_size_bytes,
        database_sha256=database_sha256,
        table_counts=table_counts,
        warning_count=warning_count,
        error_count=error_count,
    )
    if report_path is not None:
        write_json_atomic(report_path.resolve(), result.as_dict())
    if progress is not None:
        progress("complete")
    return result
