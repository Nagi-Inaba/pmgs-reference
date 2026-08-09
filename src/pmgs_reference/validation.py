"""Read-only structural validation for PMGS canonical databases."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from pmgs_reference.schema import APPLICATION_ID

_TABLES = (
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

_JPPM2026002_BASELINES = {
    "fterm_themes": (
        "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'theme'",
        2_929,
    ),
    "fterm_terms": (
        "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'term'",
        411_383,
    ),
    "fi_concepts": (
        "SELECT COUNT(*) FROM concept WHERE scheme = 'fi' AND concept_type NOT LIKE '%_reference'",
        190_384,
    ),
    "ipc_8u_concepts": (
        "SELECT COUNT(*) FROM concept "
        "WHERE scheme = 'ipc' AND edition = '8U' "
        "AND concept_type != 'concordance_reference'",
        82_540,
    ),
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    database_file: str
    database_size_bytes: int
    database_sha256: str
    integrity_check: str
    foreign_key_error_count: int
    build_error_count: int
    application_id: int
    user_version: int
    counts: dict[str, int]
    regression_checks: dict[str, dict[str, int | bool]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_validation_report(result: ValidationResult, report_path: Path) -> None:
    """Atomically write a path-safe validation report."""
    path = report_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def validate_database(database_path: Path) -> ValidationResult:
    """Validate a database without modifying it."""
    path = database_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PMGS database not found: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing"
        foreign_key_error_count = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        counts: dict[str, int] = {}
        for table in _TABLES:
            row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            assert row is not None
            counts[table] = int(row[0])
        build_error_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM build_issue WHERE severity = 'error'"
            ).fetchone()[0]
        )
        release_row = connection.execute("SELECT release_id FROM release").fetchone()
        release_id = str(release_row[0]) if release_row else ""
        regression_checks: dict[str, dict[str, int | bool]] = {}
        if release_id == "JPPM2026002":
            for name, (sql, expected) in _JPPM2026002_BASELINES.items():
                actual = int(connection.execute(sql).fetchone()[0])
                regression_checks[name] = {
                    "expected": expected,
                    "actual": actual,
                    "match": actual == expected,
                }
    finally:
        connection.close()
    valid = (
        integrity == "ok"
        and foreign_key_error_count == 0
        and build_error_count == 0
        and application_id == APPLICATION_ID
        and user_version == 1
        and counts["release"] == 1
        and counts["source_file"] > 0
        and all(bool(check["match"]) for check in regression_checks.values())
    )
    return ValidationResult(
        valid=valid,
        database_file=path.name,
        database_size_bytes=path.stat().st_size,
        database_sha256=_sha256_file(path),
        integrity_check=integrity,
        foreign_key_error_count=foreign_key_error_count,
        build_error_count=build_error_count,
        application_id=application_id,
        user_version=user_version,
        counts=counts,
        regression_checks=regression_checks,
    )
