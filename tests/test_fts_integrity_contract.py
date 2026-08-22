from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

import pmgs_reference.validation as validation_module
from pmgs_reference.validation import validate_database
from pmgs_reference.validation_core import validate_database as validate_core_database

_FTS_CHECK_NAMES = ("concept_text_fts_integrity", "document_text_fts_integrity")
_STABLE_CHECK_KEYS = {"expected", "actual", "match"}
_SUCCESS = {"expected": "consistent", "actual": "consistent", "match": True}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _remove_postings_but_keep_content(
    database: Path,
    virtual_table: str,
    source_query: str,
    shadow_columns: tuple[str, ...],
) -> int:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(source_query).fetchone()
        assert row is not None
        rowid = int(row[0])
        values = tuple(row[1:])
        connection.execute(f'DELETE FROM "{virtual_table}" WHERE rowid = ?', (rowid,))
        columns = ", ".join(("id", *shadow_columns))
        placeholders = ", ".join("?" for _ in range(len(values) + 1))
        connection.execute(
            f'INSERT INTO "{virtual_table}_content"({columns}) VALUES ({placeholders})',
            (rowid, *values),
        )
        connection.commit()
        return rowid
    finally:
        connection.close()


def test_validation_adds_stable_read_only_fts5_checks_without_mutation(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "fts.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)

    result = validate_database(database)

    assert result.valid is True
    assert all(result.checks[name] == _SUCCESS for name in _FTS_CHECK_NAMES)
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
    assert _sha256(database) == before


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((3, 44, 0), False),
        ((3, 45, 0), False),
        ((3, 45, 1), True),
    ],
)
def test_native_read_only_xintegrity_version_gate(
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int, int],
    expected: bool,
) -> None:
    monkeypatch.setattr(validation_module.sqlite3, "sqlite_version_info", version)

    assert validation_module._sqlite_integrity_covers_fts5() is expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "CREATE VIRTUAL TABLE concept_text_fts "
            "/* USING fts4(text) */ USING fts5(text)",
            "fts5",
        ),
        (
            "CREATE VIRTUAL TABLE concept_text_fts "
            "/* USING fts5(tokenize='trigram') */ USING fts4(text)",
            "fts4",
        ),
        (
            'CREATE VIRTUAL TABLE "USING fts5" -- USING fts5(text)\n'
            "USING fts4(text)",
            "fts4",
        ),
        ("CREATE TABLE concept_text_fts /* USING fts5(text) */ (text)", None),
        ("CREATE VIRTUAL TABLE concept_text_fts /* USING fts5(text)", None),
    ],
)
def test_virtual_table_module_parser_ignores_comments_and_quoted_names(
    sql: str, expected: str | None
) -> None:
    assert validation_module._virtual_table_module(sql) == expected


def test_native_xintegrity_path_does_not_create_a_database_copy(
    synthetic_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_copy(_: Path) -> dict[str, dict[str, object]]:
        raise AssertionError("native xIntegrity must not create a fallback copy")

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: True)
    monkeypatch.setattr(validation_module, "_copy_fts5_checks", fail_copy)

    result = validate_database(synthetic_database)

    assert result.valid is True
    assert all(result.checks[name] == _SUCCESS for name in _FTS_CHECK_NAMES)


def test_pre_3451_fallback_checks_a_copy_and_preserves_the_source(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "fts-fallback.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)
    calls: list[Path] = []
    real_copy_checks = validation_module._copy_fts5_checks

    def recording_copy_checks(path: Path) -> dict[str, dict[str, object]]:
        calls.append(path)
        return real_copy_checks(path)

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)
    monkeypatch.setattr(validation_module, "_copy_fts5_checks", recording_copy_checks)

    result = validate_database(database)

    assert calls == [database]
    assert result.valid is True
    assert all(result.checks[name] == _SUCCESS for name in _FTS_CHECK_NAMES)
    assert _sha256(database) == before


@pytest.mark.parametrize(
    (
        "virtual_table",
        "source_query",
        "shadow_columns",
        "integrity_check",
        "parity_check",
    ),
    [
        (
            "concept_text_fts",
            "SELECT text_id, text, revision_id, language, kind "
            "FROM concept_text WHERE length(text) >= 3 ORDER BY text_id LIMIT 1",
            ("c0", "c1", "c2", "c3"),
            "concept_text_fts_integrity",
            "concept_text_fts_parity",
        ),
        (
            "document_text_fts",
            "SELECT document_text_id, text, document_id, sequence_number "
            "FROM document_text WHERE length(text) >= 3 "
            "ORDER BY document_text_id LIMIT 1",
            ("c0", "c1", "c2"),
            "document_text_fts_integrity",
            "document_text_fts_parity",
        ),
    ],
)
def test_copy_check_rejects_missing_postings_while_content_rows_remain(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    virtual_table: str,
    source_query: str,
    shadow_columns: tuple[str, ...],
    integrity_check: str,
    parity_check: str,
) -> None:
    database = tmp_path / f"missing-postings-{virtual_table}.sqlite"
    shutil.copy2(synthetic_database, database)
    restored_rowid = _remove_postings_but_keep_content(
        database,
        virtual_table,
        source_query,
        shadow_columns,
    )
    before_validation = _sha256(database)

    read_only = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        visible = read_only.execute(
            f'SELECT rowid FROM "{virtual_table}" WHERE rowid = ?',
            (restored_rowid,),
        ).fetchone()
    finally:
        read_only.close()
    assert visible is not None

    checks = validation_module._copy_fts5_checks(database)
    check = checks[integrity_check]
    assert set(check) == _STABLE_CHECK_KEYS
    assert check["match"] is False
    assert str(check["actual"]).startswith("database_error:")
    assert database.as_posix() not in str(check["actual"])

    core_result = validate_core_database(database)
    assert core_result.checks[parity_check]["match"] is True

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)
    result = validate_database(database)

    assert result.valid is False
    assert result.checks[integrity_check] == check
    assert _sha256(database) == before_validation


def test_copy_failure_is_sanitized_and_fails_both_indexes(
    synthetic_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_backup(source: Path, destination: Path) -> None:
        raise OSError(f"cannot copy {source} to {destination}")

    monkeypatch.setattr(validation_module, "_backup_database", fail_backup)

    checks = validation_module._copy_fts5_checks(synthetic_database)

    for name in _FTS_CHECK_NAMES:
        assert checks[name] == {
            "expected": "consistent",
            "actual": "copy_error:OSError",
            "match": False,
        }
        assert synthetic_database.as_posix() not in str(checks[name])


@pytest.mark.parametrize(
    ("virtual_table", "create_sql", "insert_sql", "integrity_check"),
    [
        (
            "concept_text_fts",
            "CREATE TABLE concept_text_fts("
            "text TEXT NOT NULL, revision_id INTEGER NOT NULL, "
            "language TEXT NOT NULL, kind TEXT NOT NULL)",
            "INSERT INTO concept_text_fts(rowid, text, revision_id, language, kind) "
            "SELECT text_id, text, revision_id, language, kind FROM concept_text",
            "concept_text_fts_integrity",
        ),
        (
            "document_text_fts",
            "CREATE TABLE document_text_fts("
            "text TEXT NOT NULL, document_id TEXT NOT NULL, "
            "sequence_number INTEGER NOT NULL)",
            "INSERT INTO document_text_fts(rowid, text, document_id, sequence_number) "
            "SELECT document_text_id, text, document_id, sequence_number FROM document_text",
            "document_text_fts_integrity",
        ),
    ],
)
def test_native_path_rejects_non_fts_table_with_the_expected_name(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    virtual_table: str,
    create_sql: str,
    insert_sql: str,
    integrity_check: str,
) -> None:
    database = tmp_path / f"ordinary-{virtual_table}.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(f'DROP TABLE "{virtual_table}"')
        connection.execute(create_sql)
        connection.execute(insert_sql)
        connection.commit()
    finally:
        connection.close()

    core_result = validate_core_database(database)
    assert core_result.valid is True

    def unexpected_copy(_: Path) -> dict[str, dict[str, object]]:
        raise AssertionError("invalid FTS5 schema must fail before copying")

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: True)
    monkeypatch.setattr(validation_module, "_copy_fts5_checks", unexpected_copy)

    result = validate_database(database)

    assert result.valid is False
    assert result.checks[integrity_check] == {
        "expected": "consistent",
        "actual": "not_fts5",
        "match": False,
    }


def test_comment_spoofed_fts4_table_is_not_classified_as_fts5(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "comment-spoof.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        connection.execute('DROP TABLE "concept_text_fts"')
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE concept_text_fts "
                "/* USING fts5(text, tokenize = 'trigram') */ "
                "USING fts4(text, revision_id, language, kind)"
            )
        except sqlite3.OperationalError as exc:
            if "no such module" in str(exc).lower():
                pytest.skip("SQLite runtime does not provide FTS4")
            raise
        connection.execute(
            "INSERT INTO concept_text_fts(rowid, text, revision_id, language, kind) "
            "SELECT text_id, text, revision_id, language, kind FROM concept_text"
        )
        connection.commit()
        schema_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_schema WHERE name = 'concept_text_fts'"
            ).fetchone()[0]
        )
    finally:
        connection.close()

    assert "USING fts5" in schema_sql
    assert validation_module._virtual_table_module(schema_sql) == "fts4"

    def unexpected_copy(_: Path) -> dict[str, dict[str, object]]:
        raise AssertionError("spoofed module must fail before copying")

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: True)
    monkeypatch.setattr(validation_module, "_copy_fts5_checks", unexpected_copy)

    result = validate_database(database)

    assert result.valid is False
    assert result.checks["concept_text_fts_integrity"] == {
        "expected": "consistent",
        "actual": "not_fts5",
        "match": False,
    }


def test_unknown_fts_table_is_rejected_before_sql_interpolation(
    synthetic_database: Path,
) -> None:
    connection = sqlite3.connect(synthetic_database)
    try:
        with pytest.raises(ValueError, match="unsupported FTS5 table"):
            validation_module._fts5_special_integrity_check(
                connection,
                "malicious'; DROP TABLE release;--",
            )
    finally:
        connection.close()
