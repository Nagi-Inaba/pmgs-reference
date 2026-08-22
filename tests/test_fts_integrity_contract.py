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
_SUCCESS = {"expected": "consistent", "actual": "consistent", "match": True}


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
        assert check == _SUCCESS
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
    assert _sha256(database) == before


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


def test_pre_344_fallback_checks_a_copy_and_preserves_the_source(
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
    ("shadow_table", "integrity_check"),
    [
        ("concept_text_fts_data", "concept_text_fts_integrity"),
        ("document_text_fts_data", "document_text_fts_integrity"),
    ],
)
def test_copy_check_rejects_missing_postings_while_content_rows_remain(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shadow_table: str,
    integrity_check: str,
) -> None:
    database = tmp_path / f"corrupt-{shadow_table}.sqlite"
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

    checks = validation_module._copy_fts5_checks(database)
    check = checks[integrity_check]
    assert set(check) == _STABLE_CHECK_KEYS
    assert check["match"] is False
    assert str(check["actual"]).startswith("database_error:")
    assert database.as_posix() not in str(check["actual"])

    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)
    result = validate_database(database)

    assert result.valid is False
    assert result.checks[integrity_check]["match"] is False
    assert _sha256(database) == before_validation


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
