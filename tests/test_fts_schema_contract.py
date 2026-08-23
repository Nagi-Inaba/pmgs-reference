from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference import PMGSStore
from pmgs_reference.validation import validate_database

_EXPECTED_SCHEMA_CHECK = {
    "expected": "canonical_fts5_schema",
    "actual": "canonical_fts5_schema",
    "match": True,
}


def _replace_fts_table(
    database: Path,
    table: str,
    definition: str,
    insert_sql: str,
) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(f'DROP TABLE "{table}"')
        connection.execute(definition)
        connection.execute(insert_sql)
        connection.commit()
    finally:
        connection.close()


def test_healthy_database_exposes_both_canonical_fts5_schema_checks(
    synthetic_database: Path,
) -> None:
    result = validate_database(synthetic_database)

    assert result.valid is True
    assert result.checks["concept_text_fts_schema"] == _EXPECTED_SCHEMA_CHECK
    assert result.checks["document_text_fts_schema"] == _EXPECTED_SCHEMA_CHECK
    assert PMGSStore.open(synthetic_database).search_tokenizer == "trigram"


@pytest.mark.parametrize(
    ("table", "definition", "insert_sql", "check_name", "actual"),
    [
        (
            "concept_text_fts",
            "CREATE VIRTUAL TABLE concept_text_fts USING fts5("
            "text, revision_id, language, kind, tokenize = 'trigram')",
            "INSERT INTO concept_text_fts(rowid, text, revision_id, language, kind) "
            "SELECT text_id, text, revision_id, language, kind FROM concept_text",
            "concept_text_fts_schema",
            "unindexed_mismatch",
        ),
        (
            "concept_text_fts",
            "CREATE VIRTUAL TABLE concept_text_fts USING fts5("
            "text, language UNINDEXED, revision_id UNINDEXED, kind UNINDEXED, "
            "tokenize = 'trigram')",
            "INSERT INTO concept_text_fts(rowid, text, language, revision_id, kind) "
            "SELECT text_id, text, language, revision_id, kind FROM concept_text",
            "concept_text_fts_schema",
            "columns_mismatch",
        ),
        (
            "document_text_fts",
            "CREATE VIRTUAL TABLE document_text_fts USING fts5("
            "text, document_id UNINDEXED, sequence_number UNINDEXED, "
            "tokenize = 'unicode61')",
            "INSERT INTO document_text_fts(rowid, text, document_id, sequence_number) "
            "SELECT document_text_id, text, document_id, sequence_number FROM document_text",
            "document_text_fts_schema",
            "tokenizer_mismatch",
        ),
        (
            "document_text_fts",
            "CREATE VIRTUAL TABLE document_text_fts USING fts5("
            "text, document_id UNINDEXED, sequence_number UNINDEXED, extra UNINDEXED, "
            "tokenize = 'trigram')",
            "INSERT INTO document_text_fts("
            "rowid, text, document_id, sequence_number, extra) "
            "SELECT document_text_id, text, document_id, sequence_number, '' "
            "FROM document_text",
            "document_text_fts_schema",
            "columns_mismatch",
        ),
    ],
)
def test_validation_rejects_noncanonical_fts5_schema_without_exposing_sql(
    synthetic_database: Path,
    tmp_path: Path,
    table: str,
    definition: str,
    insert_sql: str,
    check_name: str,
    actual: str,
) -> None:
    database = tmp_path / f"{actual}-{table}.sqlite"
    shutil.copy2(synthetic_database, database)
    _replace_fts_table(database, table, definition, insert_sql)

    result = validate_database(database)

    assert result.valid is False
    assert result.checks[check_name] == {
        "expected": "canonical_fts5_schema",
        "actual": actual,
        "match": False,
    }
    serialized = str(result.checks[check_name])
    assert definition not in serialized
    assert str(database) not in serialized


@pytest.mark.parametrize(
    ("table", "definition", "insert_sql"),
    [
        (
            "concept_text_fts",
            "CREATE VIRTUAL TABLE concept_text_fts USING fts5("
            "text, revision_id, language, kind, tokenize = 'trigram')",
            "INSERT INTO concept_text_fts(rowid, text, revision_id, language, kind) "
            "SELECT text_id, text, revision_id, language, kind FROM concept_text",
        ),
        (
            "document_text_fts",
            "CREATE VIRTUAL TABLE document_text_fts USING fts5("
            "text, document_id UNINDEXED, sequence_number UNINDEXED, "
            "tokenize = 'unicode61')",
            "INSERT INTO document_text_fts(rowid, text, document_id, sequence_number) "
            "SELECT document_text_id, text, document_id, sequence_number FROM document_text",
        ),
    ],
)
def test_store_open_rejects_schema_mismatch_in_either_fts5_table(
    synthetic_database: Path,
    tmp_path: Path,
    table: str,
    definition: str,
    insert_sql: str,
) -> None:
    database = tmp_path / f"store-{table}.sqlite"
    shutil.copy2(synthetic_database, database)
    _replace_fts_table(database, table, definition, insert_sql)

    with pytest.raises(ValueError, match="search index schema is invalid") as error:
        PMGSStore.open(database)

    message = str(error.value)
    assert table in message
    assert definition not in message
    assert str(database) not in message
