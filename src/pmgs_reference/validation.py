"""Read-only structural and semantic validation for PMGS canonical databases."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from pmgs_reference.schema import APPLICATION_ID, DATABASE_USER_VERSION, SCHEMA_VERSION

_TABLES = (
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
_FTS_TABLES = ("concept_text_fts", "document_text_fts")
_INDEXES = (
    "concept_lookup_idx",
    "concept_group_idx",
    "concept_revision_concept_idx",
    "concept_revision_validity_idx",
    "concept_text_revision_idx",
    "concept_property_revision_idx",
    "relation_from_idx",
    "relation_to_idx",
    "revision_relation_from_idx",
    "revision_relation_to_idx",
    "document_kind_idx",
    "document_text_document_idx",
    "document_text_locator_idx",
    "document_link_concept_idx",
    "document_revision_link_revision_idx",
    "reference_entry_lookup_idx",
    "build_issue_severity_idx",
)
_ORIGINAL_URL = "https://www.jpo.go.jp/system/laws/sesaku/data/download.html"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    database_file: str
    database_size_bytes: int
    database_sha256: str
    logical_digest: str
    integrity_check: str
    foreign_key_error_count: int
    build_error_count: int
    application_id: int
    user_version: int
    counts: dict[str, int]
    checks: dict[str, dict[str, object]]
    regression_checks: dict[str, dict[str, int | bool]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _existing_objects(connection: sqlite3.Connection, object_type: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ?", (object_type,)
        )
    }


def logical_digest(connection: sqlite3.Connection) -> str:
    """Hash semantic table values independently of SQLite page layout and FTS shadows."""
    digest = hashlib.sha256()
    existing = _existing_objects(connection, "table")
    for table in _TABLES:
        if table not in existing:
            continue
        column_rows = list(connection.execute(f'PRAGMA table_info("{table}")'))
        columns = [str(row[1]) for row in column_rows]
        primary_key_columns = [
            str(row[1])
            for row in sorted(column_rows, key=lambda row: int(row[5]))
            if int(row[5]) > 0
        ]
        digest.update(_canonical_json({"table": table, "columns": columns}))
        select_columns = ", ".join(f'"{column}"' for column in columns)
        order_columns = ", ".join(f'"{column}"' for column in (primary_key_columns or columns))
        for row in connection.execute(
            f'SELECT {select_columns} FROM "{table}" ORDER BY {order_columns}'
        ):
            digest.update(_canonical_json(list(row)))
            digest.update(b"\n")
    return digest.hexdigest().upper()


def _check(expected: object, actual: object, match: bool | None = None) -> dict[str, object]:
    return {
        "expected": expected,
        "actual": actual,
        "match": expected == actual if match is None else match,
    }


def _scalar(connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...] = ()) -> int:
    row = connection.execute(sql, parameters).fetchone()
    return int(row[0]) if row is not None else 0


def _valid_reference_date(value: str) -> bool:
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _manifest_digest(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT source_id, relative_path, size_bytes, sha256, file_type, encoding,
               data_group, parser, status, error
        FROM source_file ORDER BY relative_path
        """
    )
    digest = hashlib.sha256()
    keys = (
        "source_id",
        "relative_path",
        "size_bytes",
        "sha256",
        "file_type",
        "encoding",
        "data_group",
        "parser",
        "status",
        "error",
    )
    for row in rows:
        digest.update(_canonical_json(dict(zip(keys, row, strict=True))))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def _lineage_violations(connection: sqlite3.Connection, existing: set[str]) -> int:
    total = 0
    for table in (
        "release_source",
        "concept",
        "concept_revision",
        "concept_text",
        "concept_property",
        "relation",
        "revision_relation",
        "document_link",
        "document_revision_link",
        "reference_entry",
    ):
        if table in existing:
            total += _scalar(
                connection,
                f'SELECT COUNT(*) FROM "{table}" '
                "WHERE source_file_id IS NULL OR source_locator IS NULL "
                "OR trim(source_locator) = ''",
            )
    return total


def _amendment_coverage_checks(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Compare normalized amendment source endpoints with every materialized link."""
    queries = {
        "ipc_amendment_relation_coverage": """
            WITH expected AS (
                SELECT sr.file_id, 'table-row:' || sr.record_number AS locator,
                       json_extract(sr.payload_json, '$.from_code') AS from_code,
                       json_extract(sr.payload_json, '$.from_version') AS from_version,
                       json_extract(sr.payload_json, '$.to_code') AS to_code,
                       json_extract(sr.payload_json, '$.to_version') AS to_version
                FROM source_record sr JOIN source_file sf ON sf.file_id = sr.file_id
                WHERE sf.data_group = 'IPC_KAISEI' AND sr.record_kind = 'html-table-row'
            ), actual AS (
                SELECT rr.source_file_id, rr.source_locator, source.normalized_code,
                       source_revision.version_indicator, target.normalized_code,
                       target_revision.version_indicator
                FROM revision_relation rr
                JOIN concept_revision source_revision
                  ON source_revision.revision_id = rr.from_revision_id
                JOIN concept source ON source.concept_id = source_revision.concept_id
                JOIN concept_revision target_revision
                  ON target_revision.revision_id = rr.to_revision_id
                JOIN concept target ON target.concept_id = target_revision.concept_id
                JOIN source_file sf ON sf.file_id = rr.source_file_id
                WHERE sf.data_group = 'IPC_KAISEI' AND rr.kind = 'amended_to'
            )
            SELECT
                (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual)) +
                (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        """,
        "ipc_amendment_document_link_coverage": """
            WITH expected AS (
                SELECT sr.file_id, json_extract(sr.payload_json, '$.from_code') AS code,
                       json_extract(sr.payload_json, '$.from_version') AS version
                FROM source_record sr JOIN source_file sf ON sf.file_id = sr.file_id
                WHERE sf.data_group = 'IPC_KAISEI' AND sr.record_kind = 'html-table-row'
                UNION
                SELECT sr.file_id, json_extract(sr.payload_json, '$.to_code'),
                       json_extract(sr.payload_json, '$.to_version')
                FROM source_record sr JOIN source_file sf ON sf.file_id = sr.file_id
                WHERE sf.data_group = 'IPC_KAISEI' AND sr.record_kind = 'html-table-row'
            ), actual AS (
                SELECT drl.source_file_id, c.normalized_code, cr.version_indicator
                FROM document_revision_link drl
                JOIN concept_revision cr ON cr.revision_id = drl.revision_id
                JOIN concept c ON c.concept_id = cr.concept_id
                JOIN source_file sf ON sf.file_id = drl.source_file_id
                WHERE sf.data_group = 'IPC_KAISEI' AND drl.kind = 'ipc_amendment'
            )
            SELECT
                (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual)) +
                (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        """,
        "fi_amendment_relation_coverage": """
            WITH expected AS (
                SELECT DISTINCT json_extract(sr.payload_json, '$.code') AS from_code,
                       json_extract(sr.payload_json, '$.translated') AS to_code
                FROM source_record sr JOIN source_file sf ON sf.file_id = sr.file_id
                WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND sr.record_kind = 'xml-element'
                  AND json_extract(sr.payload_json, '$.translated') != ''
            ), actual AS (
                SELECT DISTINCT source.normalized_code,
                       target.normalized_code
                FROM relation r
                JOIN concept source ON source.concept_id = r.from_concept_id
                JOIN concept target ON target.concept_id = r.to_concept_id
                JOIN source_file sf ON sf.file_id = r.source_file_id
                WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND r.kind = 'amended_to'
            )
            SELECT
                (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual)) +
                (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        """,
        "fi_amendment_document_link_coverage": """
            WITH expected AS (
                SELECT DISTINCT sr.file_id, json_extract(sr.payload_json, '$.code') AS code
                FROM source_record sr JOIN source_file sf ON sf.file_id = sr.file_id
                WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND sr.record_kind = 'xml-element'
                  AND json_extract(sr.payload_json, '$.code') != ''
            ), actual AS (
                SELECT dl.source_file_id, c.normalized_code
                FROM document_link dl JOIN concept c ON c.concept_id = dl.concept_id
                JOIN source_file sf ON sf.file_id = dl.source_file_id
                WHERE sf.data_group = 'FI/FI_KAISEI_DOC' AND dl.kind = 'fi_amendment'
            )
            SELECT
                (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual)) +
                (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        """,
    }
    return {name: _check(0, _scalar(connection, sql)) for name, sql in queries.items()}


def _jppm_checks(
    connection: sqlite3.Connection, reference_date: str
) -> dict[str, dict[str, int | bool]]:
    specifications = {
        "source_files": (
            "SELECT COUNT(*) FROM source_file",
            (),
            6_870,
        ),
        "source_records": (
            "SELECT COUNT(*) FROM source_record",
            (),
            4_430_638,
        ),
        "failed_sources": (
            "SELECT COUNT(*) FROM source_file WHERE status = 'failed'",
            (),
            0,
        ),
        "build_errors": (
            "SELECT COUNT(*) FROM build_issue WHERE severity = 'error'",
            (),
            0,
        ),
        "build_warnings": (
            "SELECT COUNT(*) FROM build_issue WHERE severity = 'warning'",
            (),
            124,
        ),
        "html_recovery_warnings": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'HTML_RECOVERY_USED'",
            (),
            27,
        ),
        "pdf_empty_page_warnings": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'PDF_EMPTY_PAGE'",
            (),
            41,
        ),
        "fterm_themes": (
            "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' "
            "AND concept_type = 'theme' AND record_status = 'canonical'",
            (),
            2_929,
        ),
        "fterm_terms": (
            "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' "
            "AND concept_type = 'term' AND record_status = 'canonical'",
            (),
            411_383,
        ),
        "fi_canonical_concepts": (
            "SELECT COUNT(*) FROM concept WHERE scheme = 'fi' AND record_status = 'canonical'",
            (),
            190_384,
        ),
        "ipc_8u_concepts": (
            "SELECT COUNT(*) FROM concept WHERE scheme = 'ipc' AND edition = '8U' "
            "AND record_status = 'canonical'",
            (),
            82_540,
        ),
        "ipc_8u_revisions": (
            "SELECT COUNT(*) FROM concept_revision cr JOIN concept c USING(concept_id) "
            "WHERE c.scheme = 'ipc' AND c.edition = '8U' AND c.record_status = 'canonical'",
            (),
            84_195,
        ),
        "ipc_8u_multi_version_concepts": (
            "SELECT COUNT(*) FROM (SELECT cr.concept_id FROM concept_revision cr "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'ipc' AND c.edition = '8U' "
            "AND c.record_status = 'canonical' GROUP BY cr.concept_id HAVING COUNT(*) > 1)",
            (),
            1_624,
        ),
        "ipc_8u_no_active_revision": (
            "SELECT COUNT(*) FROM concept c WHERE c.scheme = 'ipc' AND c.edition = '8U' "
            "AND c.record_status = 'canonical' AND NOT EXISTS (SELECT 1 FROM concept_revision cr "
            "WHERE cr.concept_id = c.concept_id AND (cr.valid_from IS NULL OR cr.valid_from <= ?) "
            "AND (cr.valid_to IS NULL OR cr.valid_to >= ?))",
            (reference_date, reference_date),
            2_395,
        ),
        "ipc_8u_multi_version_no_active_revision": (
            "SELECT COUNT(*) FROM (SELECT c.concept_id FROM concept c "
            "JOIN concept_revision all_revisions ON all_revisions.concept_id = c.concept_id "
            "WHERE c.scheme = 'ipc' AND c.edition = '8U' "
            "AND c.record_status = 'canonical' GROUP BY c.concept_id "
            "HAVING COUNT(*) > 1 AND NOT EXISTS (SELECT 1 FROM concept_revision active "
            "WHERE active.concept_id = c.concept_id "
            "AND (active.valid_from IS NULL OR active.valid_from <= ?) "
            "AND (active.valid_to IS NULL OR active.valid_to >= ?)))",
            (reference_date, reference_date),
            44,
        ),
        "ipc_8u_simultaneous_active": (
            "SELECT COUNT(*) FROM (SELECT c.concept_id FROM concept c "
            "JOIN concept_revision cr USING(concept_id) WHERE c.scheme = 'ipc' "
            "AND c.edition = '8U' "
            "AND c.record_status = 'canonical' AND (cr.valid_from IS NULL OR cr.valid_from <= ?) "
            "AND (cr.valid_to IS NULL OR cr.valid_to >= ?) GROUP BY c.concept_id "
            "HAVING COUNT(*) > 1)",
            (reference_date, reference_date),
            0,
        ),
        "ipc_revision_amended_to": (
            "SELECT COUNT(*) FROM revision_relation WHERE kind = 'amended_to'",
            (),
            28_799,
        ),
        "ipc_amendment_rows": (
            "SELECT COUNT(*) FROM source_record sr JOIN source_file sf "
            "ON sf.file_id = sr.file_id WHERE sf.data_group = 'IPC_KAISEI' "
            "AND sr.record_kind = 'html-table-row'",
            (),
            28_799,
        ),
        "ipc_unresolved_endpoints": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'IPC_AMENDMENT_ENDPOINT_UNRESOLVED'",
            (),
            0,
        ),
        "ipc_self_revision_relations": (
            "SELECT COUNT(*) FROM revision_relation WHERE from_revision_id = to_revision_id",
            (),
            0,
        ),
        "fi_amendment_documents": (
            "SELECT COUNT(*) FROM document WHERE kind = 'fi_amendment'",
            (),
            638,
        ),
        "fi_amendment_elements": (
            "SELECT COUNT(*) FROM source_record sr JOIN source_file sf "
            "ON sf.file_id = sr.file_id WHERE sf.data_group = 'FI/FI_KAISEI_DOC' "
            "AND sr.record_kind = 'xml-element'",
            (),
            110_590,
        ),
        "fi_document_code_pairs": (
            "SELECT COUNT(*) FROM document_link WHERE kind = 'fi_amendment'",
            (),
            97_583,
        ),
        "fi_amendment_relations": (
            "SELECT COUNT(*) FROM relation r JOIN source_file sf "
            "ON sf.file_id = r.source_file_id WHERE r.kind = 'amended_to' "
            "AND sf.data_group = 'FI/FI_KAISEI_DOC'",
            (),
            39_428,
        ),
        "fi_unresolved_endpoints": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'FI_AMENDMENT_ENDPOINT_UNRESOLVED'",
            (),
            0,
        ),
        "fterm_translation_depth_mismatches": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'FTERM_TRANSLATION_DEPTH_MISMATCH'",
            (),
            7,
        ),
        "theme_translation_sequence_mismatches": (
            "SELECT COUNT(*) FROM build_issue WHERE code = 'THEME_TRANSLATION_SEQUENCE_MISMATCH'",
            (),
            49,
        ),
    }
    checks: dict[str, dict[str, int | bool]] = {}
    for name, (sql, parameters, expected) in specifications.items():
        actual = _scalar(connection, sql, parameters)
        checks[name] = {"expected": expected, "actual": actual, "match": actual == expected}
    return checks


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
    """Validate a database read-only; malformed or partial schemas return valid=false."""
    path = database_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PMGS database not found: {path}")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    checks: dict[str, dict[str, object]] = {}
    counts: dict[str, int] = {table: 0 for table in _TABLES}
    regression_checks: dict[str, dict[str, int | bool]] = {}
    build_error_count = 0
    try:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing"
        foreign_key_error_count = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = _existing_objects(connection, "table")
        indexes = _existing_objects(connection, "index")
        required_tables = set(_TABLES + _FTS_TABLES)
        checks["application_id"] = _check(APPLICATION_ID, application_id)
        checks["user_version"] = _check(DATABASE_USER_VERSION, user_version)
        checks["required_tables"] = _check(
            sorted(required_tables), sorted(required_tables & tables), required_tables <= tables
        )
        checks["required_indexes"] = _check(
            sorted(_INDEXES), sorted(set(_INDEXES) & indexes), set(_INDEXES) <= indexes
        )
        for table in _TABLES:
            if table in tables:
                counts[table] = _scalar(connection, f'SELECT COUNT(*) FROM "{table}"')

        release_row: sqlite3.Row | None = None
        if "release" in tables:
            connection.row_factory = sqlite3.Row
            release_row = connection.execute(
                "SELECT * FROM release ORDER BY release_id LIMIT 1"
            ).fetchone()
            connection.row_factory = None
        checks["release_count"] = _check(1, counts["release"])
        schema_version = str(release_row["schema_version"]) if release_row else ""
        reference_date = str(release_row["reference_date"]) if release_row else ""
        checks["release_schema_version"] = _check(SCHEMA_VERSION, schema_version)
        checks["reference_date"] = _check(
            "valid ISO date", reference_date, _valid_reference_date(reference_date)
        )

        if release_row and "source_file" in tables:
            actual_file_count = counts["source_file"]
            actual_total_bytes = _scalar(
                connection, "SELECT COALESCE(SUM(size_bytes), 0) FROM source_file"
            )
            checks["release_source_file_count"] = _check(
                int(release_row["source_file_count"]), actual_file_count
            )
            checks["release_source_total_bytes"] = _check(
                int(release_row["source_total_bytes"]), actual_total_bytes
            )
            actual_manifest = _manifest_digest(connection)
            checks["source_manifest_sha256"] = _check(
                str(release_row["source_manifest_sha256"]), actual_manifest
            )
        else:
            for name in (
                "release_source_file_count",
                "release_source_total_bytes",
                "source_manifest_sha256",
            ):
                checks[name] = _check("available", "missing", False)

        if {"source_file", "source_record"} <= tables:
            mismatches = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM source_file sf
                WHERE sf.record_count != (
                    SELECT COUNT(*) FROM source_record sr WHERE sr.file_id = sf.file_id
                )
                """,
            )
            checks["source_file_record_counts"] = _check(0, mismatches)
        else:
            checks["source_file_record_counts"] = _check(0, "missing", False)

        amendment_tables = {
            "source_file",
            "source_record",
            "concept",
            "concept_revision",
            "relation",
            "revision_relation",
            "document_link",
            "document_revision_link",
        }
        if amendment_tables <= tables:
            checks.update(_amendment_coverage_checks(connection))
        else:
            for name in (
                "ipc_amendment_relation_coverage",
                "ipc_amendment_document_link_coverage",
                "fi_amendment_relation_coverage",
                "fi_amendment_document_link_coverage",
            ):
                checks[name] = _check(0, "missing", False)

        if {"release_source", "source_file"} <= tables:
            rows = connection.execute(
                """
                SELECT rs.owner, rs.original_url, rs.attribution,
                       sf.relative_path, rs.source_locator
                FROM release_source rs JOIN source_file sf ON sf.file_id = rs.source_file_id
                """
            ).fetchall()
            valid_source = len(rows) == 1
            if valid_source:
                owner, url, attribution, relative_path, locator = (str(value) for value in rows[0])
                valid_source = (
                    owner == "JPO"
                    and url == _ORIGINAL_URL
                    and bool(attribution)
                    and attribution == attribution.strip()
                    and Path(relative_path).name.upper() == "COPYRGHT"
                    and locator == "file"
                )
            checks["release_source_COPYRGHT_lineage"] = _check(True, valid_source)
        else:
            checks["release_source_COPYRGHT_lineage"] = _check(True, False)

        if {"concept", "concept_revision"} <= tables:
            base_violations = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM concept c
                WHERE (c.scheme IN ('fi', 'fterm') OR (c.scheme = 'ipc' AND c.edition != '8U'))
                AND (SELECT COUNT(*) FROM concept_revision cr
                     WHERE cr.concept_id = c.concept_id) != 1
                """,
            ) + _scalar(
                connection,
                """
                SELECT COUNT(*) FROM concept c
                WHERE (c.scheme IN ('fi', 'fterm') OR (c.scheme = 'ipc' AND c.edition != '8U'))
                AND NOT EXISTS (SELECT 1 FROM concept_revision cr
                                WHERE cr.concept_id = c.concept_id AND cr.version_indicator = '')
                """,
            )
            checks["base_revision_rules"] = _check(0, base_violations)
            invalid_version = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM concept_revision cr JOIN concept c USING(concept_id)
                WHERE c.scheme = 'ipc' AND c.edition = '8U' AND c.record_status = 'canonical'
                AND cr.version_indicator = ''
                """,
            )
            checks["ipc_8u_version_indicators"] = _check(0, invalid_version)
            ipc_revision_sequences = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM concept_revision cr JOIN concept c USING(concept_id)
                WHERE c.scheme = 'ipc' AND cr.sequence_number IS NOT NULL
                """,
            )
            checks["ipc_revision_sequence_is_text_scoped"] = _check(0, ipc_revision_sequences)
            if _valid_reference_date(reference_date):
                simultaneous = _scalar(
                    connection,
                    """
                    SELECT COUNT(*) FROM (
                        SELECT concept_id FROM concept_revision
                        WHERE (valid_from IS NULL OR valid_from <= ?)
                          AND (valid_to IS NULL OR valid_to >= ?)
                        GROUP BY concept_id HAVING COUNT(*) > 1
                    )
                    """,
                    (reference_date, reference_date),
                )
                checks["active_at_reference_date_unique"] = _check(0, simultaneous)
            else:
                checks["active_at_reference_date_unique"] = _check(
                    0, "invalid reference date", False
                )
        else:
            for name in (
                "base_revision_rules",
                "ipc_8u_version_indicators",
                "ipc_revision_sequence_is_text_scoped",
                "active_at_reference_date_unique",
            ):
                checks[name] = _check(0, "missing", False)

        relation_self = (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM relation WHERE from_concept_id = to_concept_id "
                "AND kind != 'amended_to'",
            )
            if "relation" in tables
            else -1
        )
        revision_self = (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM revision_relation WHERE from_revision_id = to_revision_id",
            )
            if "revision_relation" in tables
            else -1
        )
        checks["relation_self_links"] = _check(0, relation_self, relation_self == 0)
        checks["revision_relation_self_links"] = _check(0, revision_self, revision_self == 0)

        checks["foreign_key_orphans"] = _check(0, foreign_key_error_count)
        lineage = _lineage_violations(connection, tables)
        checks["source_lineage"] = _check(0, lineage)

        if {"concept_text", "concept_text_fts"} <= tables:
            concept_fts_errors = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM concept_text ct
                LEFT JOIN concept_text_fts f ON f.rowid = ct.text_id
                WHERE f.rowid IS NULL OR f.text != ct.text OR f.revision_id != ct.revision_id
                   OR f.language != ct.language OR f.kind != ct.kind
                """,
            ) + _scalar(
                connection,
                "SELECT COUNT(*) FROM concept_text_fts f "
                "LEFT JOIN concept_text ct ON ct.text_id = f.rowid WHERE ct.text_id IS NULL",
            )
            checks["concept_text_fts_parity"] = _check(0, concept_fts_errors)
        else:
            checks["concept_text_fts_parity"] = _check(0, "missing", False)
        if {"document_text", "document_text_fts"} <= tables:
            document_fts_errors = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM document_text dt
                LEFT JOIN document_text_fts f ON f.rowid = dt.document_text_id
                WHERE f.rowid IS NULL OR f.text != dt.text OR f.document_id != dt.document_id
                   OR f.sequence_number != dt.sequence_number
                """,
            ) + _scalar(
                connection,
                "SELECT COUNT(*) FROM document_text_fts f LEFT JOIN document_text dt "
                "ON dt.document_text_id = f.rowid WHERE dt.document_text_id IS NULL",
            )
            checks["document_text_fts_parity"] = _check(0, document_fts_errors)
        else:
            checks["document_text_fts_parity"] = _check(0, "missing", False)

        build_error_count = (
            _scalar(connection, "SELECT COUNT(*) FROM build_issue WHERE severity = 'error'")
            if "build_issue" in tables
            else -1
        )
        checks["build_errors"] = _check(0, build_error_count, build_error_count == 0)
        if (
            release_row
            and str(release_row["release_id"]) == "JPPM2026002"
            and {
                "concept",
                "concept_revision",
                "revision_relation",
            }
            <= tables
        ):
            regression_checks = _jppm_checks(connection, reference_date)
            for name, check in regression_checks.items():
                checks[f"jppm_{name}"] = dict(check)
        database_logical_digest = logical_digest(connection)
    except (sqlite3.DatabaseError, IndexError, KeyError, TypeError, ValueError) as exc:
        integrity = f"database_error:{type(exc).__name__}"
        foreign_key_error_count = -1
        application_id = 0
        user_version = 0
        database_logical_digest = ""
        checks["validation_execution"] = _check("success", type(exc).__name__, False)
    finally:
        connection.close()
    valid = (
        integrity == "ok"
        and foreign_key_error_count == 0
        and bool(checks)
        and all(bool(check.get("match")) for check in checks.values())
    )
    return ValidationResult(
        valid=valid,
        database_file=path.name,
        database_size_bytes=path.stat().st_size,
        database_sha256=_sha256_file(path),
        logical_digest=database_logical_digest,
        integrity_check=integrity,
        foreign_key_error_count=foreign_key_error_count,
        build_error_count=build_error_count,
        application_id=application_id,
        user_version=user_version,
        counts=counts,
        checks=checks,
        regression_checks=regression_checks,
    )
