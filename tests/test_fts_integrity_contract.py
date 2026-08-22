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


def test_read_only_validation_scans_both_fts5_inverted_indexes_without_mutation(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "fts.sqlite"
    shutil.copy2(synthetic_database, database)
    before = _sha256(database)

    result = validate_database(database)

    assert result.valid is True
    assert result.checks["concept_text_fts_integrity"]["match"] is True
    assert result.checks["document_text_fts_integrity"]["match"] is True
    assert result.checks["concept_text_fts_parity"]["match"] is True
    assert result.checks["document_text_fts_parity"]["match"] is True
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
def test_validation_rejects_corrupt_fts_shadow_index_on_all_supported_sqlite_versions(
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
    assert result.checks[integrity_check]["match"] is False
    assert str(result.checks[integrity_check]["actual"]).startswith("database_error:")
    assert result.checks[parity_check]["match"] is True
    assert _sha256(database) == before_validation
