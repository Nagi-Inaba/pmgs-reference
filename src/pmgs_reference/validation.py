"""Public validation facade with cross-version read-only FTS5 integrity checks."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from pmgs_reference.validation_core import (
    ValidationResult,
    logical_digest,
    validate_database as _validate_core_database,
    write_validation_report,
)

__all__ = [
    "ValidationResult",
    "logical_digest",
    "validate_database",
    "write_validation_report",
]

_FTS_TABLES = ("concept_text_fts", "document_text_fts")
_SQLITE_FTS_XINTEGRITY_VERSION = (3, 44, 0)


def _check(expected: object, actual: object, match: bool | None = None) -> dict[str, object]:
    return {
        "expected": expected,
        "actual": actual,
        "match": expected == actual if match is None else match,
    }


def _sqlite_integrity_covers_fts5() -> bool:
    """Return whether PRAGMA integrity_check invokes the FTS5 xIntegrity hook."""
    return sqlite3.sqlite_version_info >= _SQLITE_FTS_XINTEGRITY_VERSION


def _fts5_index_integrity(
    connection: sqlite3.Connection,
    table: str,
    core_integrity: str,
) -> dict[str, object]:
    """Validate one FTS5 inverted index without writing to the source database."""
    if table not in _FTS_TABLES:
        raise ValueError("unsupported FTS5 table")

    if core_integrity == "ok" and _sqlite_integrity_covers_fts5():
        return {
            "expected": "readable",
            "actual": "covered_by_pragma_integrity_check",
            "match": True,
            "method": "pragma_xintegrity",
            "sqlite_version": sqlite3.sqlite_version,
        }

    vocabulary = f"__pmgs_{table}_integrity_vocab"
    drop_sql = f'DROP TABLE IF EXISTS temp."{vocabulary}"'
    try:
        connection.execute(drop_sql)
        connection.execute(
            f'CREATE VIRTUAL TABLE temp."{vocabulary}" '
            f"USING fts5vocab(main, '{table}', 'row')"
        )
        row = connection.execute(
            f'SELECT COUNT(*), COALESCE(SUM(doc), 0), COALESCE(SUM(cnt), 0) '
            f'FROM temp."{vocabulary}"'
        ).fetchone()
        if row is None:
            return {
                "expected": "readable",
                "actual": "missing_result",
                "match": False,
                "method": "fts5vocab",
                "sqlite_version": sqlite3.sqlite_version,
            }
        return {
            "expected": "readable",
            "actual": "readable",
            "match": True,
            "method": "fts5vocab",
            "sqlite_version": sqlite3.sqlite_version,
            "term_count": int(row[0]),
            "term_document_pairs": int(row[1]),
            "token_occurrences": int(row[2]),
        }
    except sqlite3.DatabaseError as exc:
        return {
            "expected": "readable",
            "actual": f"database_error:{type(exc).__name__}",
            "match": False,
            "method": "fts5vocab",
            "sqlite_version": sqlite3.sqlite_version,
        }
    finally:
        try:
            connection.execute(drop_sql)
        except sqlite3.DatabaseError:
            pass


def _fts5_checks(database_path: Path, core_integrity: str) -> dict[str, dict[str, object]]:
    path = database_path.resolve()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        return {
            f"{table}_integrity": (
                _fts5_index_integrity(connection, table, core_integrity)
                if table in tables
                else _check("readable", "missing", False)
            )
            for table in _FTS_TABLES
        }
    except sqlite3.DatabaseError as exc:
        failure = {
            "expected": "readable",
            "actual": f"database_error:{type(exc).__name__}",
            "match": False,
            "method": "connection",
            "sqlite_version": sqlite3.sqlite_version,
        }
        return {f"{table}_integrity": dict(failure) for table in _FTS_TABLES}
    finally:
        connection.close()


def validate_database(database_path: Path) -> ValidationResult:
    """Run the existing validator and add a read-only FTS5 inverted-index gate."""
    result = _validate_core_database(database_path)
    fts_checks = _fts5_checks(database_path, result.integrity_check)
    checks = dict(result.checks)
    checks.update(fts_checks)
    fts_valid = all(bool(check.get("match")) for check in fts_checks.values())
    return replace(result, valid=result.valid and fts_valid, checks=checks)
