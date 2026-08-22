from __future__ import annotations

from pathlib import Path


VALIDATION_HELPERS = '''def _sqlite_integrity_covers_fts5() -> bool:
    """Return whether PRAGMA integrity_check invokes FTS5 xIntegrity."""
    return sqlite3.sqlite_version_info >= (3, 44, 0)


def _fts5_index_integrity(
    connection: sqlite3.Connection,
    table: str,
    core_integrity: str,
) -> dict[str, object]:
    """Validate one FTS5 index without writing to the source database."""
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
            f'SELECT COUNT(*), COALESCE(SUM(doc), 0), '
            f'COALESCE(SUM(cnt), 0) FROM temp."{vocabulary}"'
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


'''


TEST_CONTENT = '''from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

import pmgs_reference.validation as validation_module
from pmgs_reference.validation import validate_database


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def test_validation_uses_a_read_only_fts5_integrity_gate_without_mutation(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "fts.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)

    result = validate_database(database)

    assert result.valid is True
    for name in ("concept_text_fts_integrity", "document_text_fts_integrity"):
        check = result.checks[name]
        assert check["match"] is True
        assert check["method"] in {"pragma_xintegrity", "fts5vocab"}
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
    assert _sha256(database) == before


def test_validation_exercises_the_pre_344_read_only_fallback(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "fts-fallback.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)
    monkeypatch.setattr(validation_module, "_sqlite_integrity_covers_fts5", lambda: False)

    result = validate_database(database)

    assert result.valid is True
    for name in ("concept_text_fts_integrity", "document_text_fts_integrity"):
        check = result.checks[name]
        assert check["match"] is True
        assert check["method"] == "fts5vocab"
        assert check["actual"] == "readable"
    assert _sha256(database) == before


@pytest.mark.parametrize(
    ("shadow_table", "integrity_check", "parity_check"),
    [
        (
            "concept_text_fts_data",
            "concept_text_fts_integrity",
            "concept_text_fts_parity",
        ),
        (
            "document_text_fts_data",
            "document_text_fts_integrity",
            "document_text_fts_parity",
        ),
    ],
)
def test_validation_rejects_corrupt_fts_shadow_index_on_supported_sqlite_versions(
    synthetic_database: Path,
    tmp_path: Path,
    shadow_table: str,
    integrity_check: str,
    parity_check: str,
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

    result = validate_database(database)

    assert result.valid is False
    check = result.checks[integrity_check]
    assert check["match"] is False
    assert check["method"] == "fts5vocab"
    assert str(check["actual"]).startswith("database_error:")
    assert result.checks[parity_check]["match"] is True
    assert _sha256(database) == before_validation
'''


VERIFICATION_CONTENT = '''# FTS5 inverted-index validation — 2026-08-22

対象Issue: #31

## 契約

- SQLite 3.44以降でcore integrityが正常な場合、`PRAGMA integrity_check`によるFTS5 `xIntegrity`を利用する。
- 旧SQLite、またはcore integrityが異常な場合、`temp` schemaの`fts5vocab`から転置索引を全走査する。
- canonical databaseは`mode=ro`で開いたままにし、検証前後のSHA-256を一致させる。
- `concept_text_fts`と`document_text_fts`を個別checkとしてreportへ記録する。
- failure情報は例外型を用いた安定値に限定し、path、page内容、query textを含めない。

## 回帰テスト

- 正常な両indexの検証とdatabase hash不変性。
- SQLite 3.44未満相当のfallback経路。
- FTS5 shadow dataだけを壊し、可視row parityが成功したまま専用index checkが失敗すること。
- supported Python / OS matrixでの同一契約。

## 残余リスク

`fts5vocab` fallbackはindexを読取走査して構造破損を検出する。SQLite 3.44以降の`xIntegrity`と同一実装ではないため、旧SQLite固有の未観測破損形式が存在する可能性は残る。正本を書込み可能に開いてFTS5 special commandを実行する方式は採用しない。
'''


def apply() -> None:
    validation_path = Path("src/pmgs_reference/validation.py")
    text = validation_path.read_text(encoding="utf-8")

    if "def _fts5_index_integrity(" not in text:
        anchor = "def _valid_reference_date(value: str) -> bool:\n"
        if text.count(anchor) != 1:
            raise SystemExit("validation helper anchor mismatch")
        text = text.replace(anchor, VALIDATION_HELPERS + anchor, 1)

    old_integrity = '''    try:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "missing"
        foreign_key_error_count = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
'''
    new_integrity = '''    try:
        try:
            integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            integrity = f"database_error:{type(exc).__name__}"
        else:
            integrity = str(integrity_row[0]) if integrity_row else "missing"
        foreign_key_error_count = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
'''
    if "integrity = f\"database_error:{type(exc).__name__}\"" not in text:
        if text.count(old_integrity) != 1:
            raise SystemExit("integrity pragma anchor mismatch")
        text = text.replace(old_integrity, new_integrity, 1)

    old_checks = '''        checks["required_indexes"] = _check(
            sorted(_INDEXES), sorted(set(_INDEXES) & indexes), set(_INDEXES) <= indexes
        )
        for table in _TABLES:
'''
    new_checks = '''        checks["required_indexes"] = _check(
            sorted(_INDEXES), sorted(set(_INDEXES) & indexes), set(_INDEXES) <= indexes
        )
        for fts_table in _FTS_TABLES:
            check_name = f"{fts_table}_integrity"
            checks[check_name] = (
                _fts5_index_integrity(connection, fts_table, integrity)
                if fts_table in tables
                else _check("readable", "missing", False)
            )
        for table in _TABLES:
'''
    if 'check_name = f"{fts_table}_integrity"' not in text:
        if text.count(old_checks) != 1:
            raise SystemExit("FTS check insertion anchor mismatch")
        text = text.replace(old_checks, new_checks, 1)

    validation_path.write_text(text, encoding="utf-8")
    Path("tests/test_fts_integrity_contract.py").write_text(TEST_CONTENT, encoding="utf-8")
    Path("docs/verification/fts-integrity-2026-08-22.md").write_text(
        VERIFICATION_CONTENT, encoding="utf-8"
    )


if __name__ == "__main__":
    apply()
