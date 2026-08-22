from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

import pmgs_reference.validation as validation_module
from pmgs_reference.validation import validate_database


_FTS_CHECK_NAMES = ("concept_text_fts_integrity", "document_text_fts_integrity")
_STABLE_CHECK_KEYS = {"expected", "actual", "match"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def test_validation_adds_stable_read_only_fts5_checks_without_mutation(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "fts.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)

    result = validate_database(database)

    assert result.valid is True
    for name in _FTS_CHECK_NAMES:
        check = result.checks[name]
        assert set(check) == _STABLE_CHECK_KEYS
        assert check == {"expected": "readable", "actual": "readable", "match": True}
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
    assert _sha256(database) == before


def test_native_xintegrity_path_does_not_start_a_fallback_scan(
    synthetic_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    connection = sqlite3.connect(f"file:{synthetic_database.as_posix()}?mode=ro", uri=True)
    connection.set_trace_callback(statements.append)
    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: True)
    try:
        check = validation_module._fts5_index_integrity(
            connection, "concept_text_fts", "ok"
        )
    finally:
        connection.close()

    assert check == {"expected": "readable", "actual": "readable", "match": True}
    assert not any("fts5vocab" in statement.lower() for statement in statements)


def test_pre_344_fallback_reads_both_indexes_without_mutation(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "fts-fallback.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)
    statements: list[str] = []
    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)

    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.set_trace_callback(statements.append)
    try:
        for table in ("concept_text_fts", "document_text_fts"):
            check = validation_module._fts5_index_integrity(connection, table, "ok")
            assert check == {
                "expected": "readable",
                "actual": "readable",
                "match": True,
            }
    finally:
        connection.close()

    traced = "\n".join(statements).lower()
    assert "fts5vocab(main, 'concept_text_fts', 'row')" in traced
    assert "fts5vocab(main, 'document_text_fts', 'row')" in traced
    assert _sha256(database) == before


@pytest.mark.parametrize(
    ("shadow_table", "virtual_table", "integrity_check"),
    [
        (
            "concept_text_fts_data",
            "concept_text_fts",
            "concept_text_fts_integrity",
        ),
        (
            "document_text_fts_data",
            "document_text_fts",
            "document_text_fts_integrity",
        ),
    ],
)
def test_fallback_rejects_corrupt_fts_shadow_index_without_mutation(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shadow_table: str,
    virtual_table: str,
    integrity_check: str,
) -> None:
    database = tmp_path / f"corrupt-{virtual_table}.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        deleted = connection.execute(
            f'DELETE FROM "{shadow_table}" WHERE id = (SELECT MAX(id) FROM "{shadow_table}")'
        ).rowcount
        connection.commit()
    finally:
        connection.close()
    assert deleted == 1
    before_validation = _sha256(database)
    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)

    read_only = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        fallback = validation_module._fts5_index_integrity(read_only, virtual_table, "ok")
    finally:
        read_only.close()

    assert set(fallback) == _STABLE_CHECK_KEYS
    assert fallback["match"] is False
    assert str(fallback["actual"]).startswith("database_error:")
    assert database.as_posix() not in str(fallback["actual"])

    result = validate_database(database)
    assert result.valid is False
    assert set(result.checks[integrity_check]) == _STABLE_CHECK_KEYS
    assert result.checks[integrity_check]["match"] is False
    assert _sha256(database) == before_validation


def test_unknown_fts_table_is_rejected_before_sql_interpolation(
    synthetic_database: Path,
) -> None:
    connection = sqlite3.connect(f"file:{synthetic_database.as_posix()}?mode=ro", uri=True)
    try:
        with pytest.raises(ValueError, match="unsupported FTS5 table"):
            validation_module._fts5_index_integrity(
                connection,
                "malicious'; DROP TABLE release;--",
                "ok",
            )
    finally:
        connection.close()
