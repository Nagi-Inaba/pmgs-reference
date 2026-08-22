from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

from pmgs_reference.validation import validate_database


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_validation_checks_both_fts5_inverted_indexes_without_mutating_database(
    synthetic_database: Path,
) -> None:
    before = _sha256(synthetic_database)

    result = validate_database(synthetic_database)

    assert result.valid is True
    assert result.checks["concept_text_fts_integrity"]["match"] is True
    assert result.checks["document_text_fts_integrity"]["match"] is True
    assert _sha256(synthetic_database) == before


def test_shadow_index_corruption_fails_even_when_visible_rows_still_match(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "corrupt-fts.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        visible_before = connection.execute(
            "SELECT rowid, text, revision_id, language, kind FROM concept_text_fts LIMIT 1"
        ).fetchone()
        connection.execute("DELETE FROM concept_text_fts_idx")
        connection.commit()
        visible_after = connection.execute(
            "SELECT rowid, text, revision_id, language, kind FROM concept_text_fts LIMIT 1"
        ).fetchone()
    finally:
        connection.close()

    assert visible_after == visible_before
    result = validate_database(database)

    assert result.valid is False
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["concept_text_fts_integrity"]["match"] is False
    assert result.checks["document_text_fts_integrity"]["match"] is True


def test_fts_integrity_failure_is_reported_without_internal_paths(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "corrupt-document-fts.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("DELETE FROM document_text_fts_idx")
        connection.commit()
    finally:
        connection.close()

    result = validate_database(database)
    check = result.checks["document_text_fts_integrity"]

    assert check["match"] is False
    assert "expected" in check
    assert "actual" in check
    assert str(tmp_path) not in str(check)
