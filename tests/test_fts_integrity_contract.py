from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference.validation import validate_database


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def test_sqlite_integrity_check_covers_both_fts5_inverted_indexes_without_mutation(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "fts.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)

    result = validate_database(database)

    assert result.valid is True
    assert result.integrity_check == "ok"
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
    assert _sha256(database) == before


@pytest.mark.parametrize(
    ("shadow_table", "expected_virtual_table"),
    [
        ("concept_text_fts_data", "concept_text_fts"),
        ("document_text_fts_data", "document_text_fts"),
    ],
)
def test_validation_rejects_corrupt_fts_shadow_index_even_when_content_rows_remain(
    synthetic_database: Path,
    tmp_path: Path,
    shadow_table: str,
    expected_virtual_table: str,
) -> None:
    database = tmp_path / f"corrupt-{expected_virtual_table}.sqlite"
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

    result = validate_database(database)

    assert result.valid is False
    assert result.integrity_check == (
        f"malformed inverted index for FTS5 table main.{expected_virtual_table}"
    )
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
