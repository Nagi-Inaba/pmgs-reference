"""Public validation facade with cross-version read-only FTS5 integrity checks."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

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

_FTS_TABLES = ("concept_text_fts", "document_text_fts")
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


def _sql_tokens(sql: str) -> list[tuple[str, str]]:
    """Tokenize enough SQLite DDL to identify a virtual-table module safely."""
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                return []
            index = end + 2
            continue
        if character == "'":
            index += 1
            while index < length:
                if sql[index] == "'":
                    if index + 1 < length and sql[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            tokens.append(("string", ""))
            continue
        if character in {'"', "`", "["}:
            closing = "]" if character == "[" else character
            index += 1
            value: list[str] = []
            while index < length:
                if sql[index] == closing:
                    if index + 1 < length and sql[index + 1] == closing:
                        value.append(closing)
                        index += 2
                        continue
                    index += 1
                    break
                value.append(sql[index])
                index += 1
            tokens.append(("identifier", "".join(value).casefold()))
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append(("word", sql[index:end].casefold()))
            index = end
            continue
        tokens.append(("symbol", character))
        index += 1
    return tokens


def _virtual_table_module(sql: str) -> str | None:
    """Return the actual module token from CREATE VIRTUAL TABLE DDL."""
    tokens = _sql_tokens(sql)
    position = 0

    def take_word(value: str) -> bool:
        nonlocal position
        if position >= len(tokens) or tokens[position] != ("word", value):
            return False
        position += 1
        return True

    if not take_word("create"):
        return None
    if position < len(tokens) and tokens[position] in {
        ("word", "temp"),
        ("word", "temporary"),
    }:
        position += 1
    if not take_word("virtual") or not take_word("table"):
        return None
    if position + 2 < len(tokens) and tokens[position : position + 3] == [
        ("word", "if"),
        ("word", "not"),
        ("word", "exists"),
    ]:
        position += 3
    if position >= len(tokens) or tokens[position][0] not in {"word", "identifier"}:
        return None
    position += 1
    if position + 1 < len(tokens) and tokens[position] == ("symbol", "."):
        if tokens[position + 1][0] not in {"word", "identifier"}:
            return None
        position += 2
    if not take_word("using"):
        return None
    if position >= len(tokens) or tokens[position][0] not in {"word", "identifier"}:
        return None
    module = tokens[position][1]
    position += 1
    if position >= len(tokens) or tokens[position] != ("symbol", "("):
        return None
    return module


def _fts5_table_statuses(connection: sqlite3.Connection) -> dict[str, str]:
    rows = {
        str(row[0]): str(row[1]) if row[1] is not None else ""
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type = 'table' AND name IN (?, ?)",
            _FTS_TABLES,
        )
    }
    statuses: dict[str, str] = {}
    for table in _FTS_TABLES:
        if table not in rows:
            statuses[table] = "missing"
        elif _virtual_table_module(rows[table]) != "fts5":
            statuses[table] = "not_fts5"
        else:
            statuses[table] = "fts5"
    return statuses


def _schema_failure_results(statuses: dict[str, str]) -> dict[str, dict[str, object]]:
    return {
        f"{table}_integrity": (
            _check("consistent", "not_checked", False)
            if status == "fts5"
            else _check("consistent", status, False)
        )
        for table, status in statuses.items()
    }


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
    if all(status == "fts5" for status in statuses.values()):
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
                if not all(status == "fts5" for status in statuses.values()):
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
    """Run the existing validator and add a read-only FTS5 inverted-index gate."""
    result = _validate_core_database(database_path)
    fts_checks = _fts5_checks(database_path, result.integrity_check)
    checks = dict(result.checks)
    checks.update(fts_checks)
    fts_valid = all(bool(check.get("match")) for check in fts_checks.values())
    return replace(result, valid=result.valid and fts_valid, checks=checks)
