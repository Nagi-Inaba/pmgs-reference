"""Public validation facade with cross-version read-only FTS5 integrity checks."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from pmgs_reference.fts_schema import (
    CANONICAL_FTS5_SCHEMAS,
    inspect_fts5_schemas,
    virtual_table_module,
)
from pmgs_reference.validation_core import (
    ValidationResult,
    logical_digest,
    write_validation_report,
)
from pmgs_reference.validation_core import validate_database as _validate_core_database

__all__ = [
    "ValidationResult",
    "logical_digest",
    "validate_database",
    "write_validation_report",
]

_FTS_TABLES = tuple(CANONICAL_FTS5_SCHEMAS)
_CANONICAL_FTS5_SCHEMA = "canonical_fts5_schema"
_SQLITE_READ_ONLY_XINTEGRITY_VERSION = (3, 45, 1)


def _check(expected: object, actual: object, match: bool | None = None) -> dict[str, object]:
    return {
        "expected": expected,
        "actual": actual,
        "match": expected == actual if match is None else match,
    }


def _sqlite_integrity_covers_fts5() -> bool:
    """Return whether read-only PRAGMA integrity_check reliably invokes FTS5 xIntegrity."""
    return sqlite3.sqlite_version_info >= _SQLITE_READ_ONLY_XINTEGRITY_VERSION


def _virtual_table_module(sql: str) -> str | None:
    """Compatibility wrapper for the comment-safe shared DDL parser."""
    return virtual_table_module(sql)


def _fts5_table_statuses(connection: sqlite3.Connection) -> dict[str, str]:
    return inspect_fts5_schemas(connection)


def _fts5_schema_checks_from_statuses(
    statuses: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        f"{table}_schema": _check(
            _CANONICAL_FTS5_SCHEMA,
            status,
            status == _CANONICAL_FTS5_SCHEMA,
        )
        for table, status in statuses.items()
    }


def _schema_failure_results(statuses: dict[str, str]) -> dict[str, dict[str, object]]:
    return {
        f"{table}_integrity": (
            _check("consistent", "not_checked", False)
            if status == _CANONICAL_FTS5_SCHEMA
            else _check("consistent", status, False)
        )
        for table, status in statuses.items()
    }


def _fts5_schema_checks(database_path: Path) -> dict[str, dict[str, object]]:
    path = database_path.resolve()
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        actual = f"database_error:{type(exc).__name__}"
        return {
            f"{table}_schema": _check(_CANONICAL_FTS5_SCHEMA, actual, False)
            for table in _FTS_TABLES
        }
    try:
        statuses = _fts5_table_statuses(connection)
    except sqlite3.DatabaseError as exc:
        actual = f"database_error:{type(exc).__name__}"
        return {
            f"{table}_schema": _check(_CANONICAL_FTS5_SCHEMA, actual, False)
            for table in _FTS_TABLES
        }
    finally:
        connection.close()
    return _fts5_schema_checks_from_statuses(statuses)


def _source_schema_failures(
    database_path: Path,
) -> dict[str, dict[str, object]] | None:
    path = database_path.resolve()
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        return _database_failure(exc)
    try:
        statuses = _fts5_table_statuses(connection)
    except sqlite3.DatabaseError as exc:
        return _database_failure(exc)
    finally:
        connection.close()
    if all(status == _CANONICAL_FTS5_SCHEMA for status in statuses.values()):
        return None
    return _schema_failure_results(statuses)


def _fts5_special_integrity_check(
    connection: sqlite3.Connection,
    table: str,
) -> dict[str, object]:
    """Run FTS5's content-versus-index check on a disposable database copy."""
    if table not in _FTS_TABLES:
        raise ValueError("unsupported FTS5 table")
    try:
        connection.execute(
            f'INSERT INTO "{table}"("{table}") VALUES (?)',
            ("integrity-check",),
        )
    except sqlite3.DatabaseError as exc:
        with suppress(sqlite3.DatabaseError):
            connection.rollback()
        return _check("consistent", f"database_error:{type(exc).__name__}", False)
    connection.rollback()
    return _check("consistent", "consistent")


def _database_failure(exc: sqlite3.DatabaseError) -> dict[str, dict[str, object]]:
    failure = _check("consistent", f"database_error:{type(exc).__name__}", False)
    return {f"{table}_integrity": dict(failure) for table in _FTS_TABLES}


def _copy_failure(
    exc: OSError | sqlite3.DatabaseError,
) -> dict[str, dict[str, object]]:
    failure = _check("consistent", f"copy_error:{type(exc).__name__}", False)
    return {f"{table}_integrity": dict(failure) for table in _FTS_TABLES}


def _backup_database(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    try:
        source.execute("PRAGMA query_only = ON")
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _copy_fts5_checks(database_path: Path) -> dict[str, dict[str, object]]:
    """Copy the database, then run exact FTS5 integrity checks on the copy."""
    path = database_path.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="pmgs-reference-fts5-") as directory:
            copy_path = Path(directory) / "validation.sqlite"
            _backup_database(path, copy_path)
            connection = sqlite3.connect(copy_path)
            try:
                statuses = _fts5_table_statuses(connection)
                if not all(status == _CANONICAL_FTS5_SCHEMA for status in statuses.values()):
                    return _schema_failure_results(statuses)
                return {
                    f"{table}_integrity": _fts5_special_integrity_check(connection, table)
                    for table in _FTS_TABLES
                }
            finally:
                connection.close()
    except (OSError, sqlite3.DatabaseError) as exc:
        return _copy_failure(exc)


def _fts5_checks(database_path: Path, core_integrity: str) -> dict[str, dict[str, object]]:
    schema_failures = _source_schema_failures(database_path)
    if schema_failures is not None:
        return schema_failures
    if core_integrity == "ok" and _sqlite_integrity_covers_fts5():
        success = _check("consistent", "consistent")
        return {f"{table}_integrity": dict(success) for table in _FTS_TABLES}
    return _copy_fts5_checks(database_path)


def validate_database(database_path: Path) -> ValidationResult:
    """Run the existing validator and add canonical FTS5 schema and integrity gates."""
    result = _validate_core_database(database_path)
    schema_checks = _fts5_schema_checks(database_path)
    integrity_checks = _fts5_checks(database_path, result.integrity_check)
    checks = dict(result.checks)
    checks.update(schema_checks)
    checks.update(integrity_checks)
    fts_checks = {**schema_checks, **integrity_checks}
    fts_valid = all(bool(check.get("match")) for check in fts_checks.values())
    return replace(result, valid=result.valid and fts_valid, checks=checks)
