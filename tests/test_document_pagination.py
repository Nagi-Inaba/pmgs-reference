from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference import PMGSQueryError, PMGSStore
from pmgs_reference.cli import main
from pmgs_reference.mcp_server import create_server


def _seed_large_document(database: Path) -> tuple[str, int]:
    connection = sqlite3.connect(database)
    try:
        document_id = str(
            connection.execute(
                "SELECT d.document_id FROM document d "
                "JOIN document_text dt ON dt.document_id = d.document_id "
                "GROUP BY d.document_id ORDER BY d.document_id LIMIT 1"
            ).fetchone()[0]
        )
        source_file_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        release_id = str(connection.execute("SELECT release_id FROM release LIMIT 1").fetchone()[0])
        max_sequence = int(
            connection.execute(
                "SELECT MAX(sequence_number) FROM document_text WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
        )
        for index in range(1, 206):
            sequence = max_sequence + index
            locator = f"synthetic-section:{index}"
            connection.execute(
                "INSERT INTO document_text(document_id, sequence_number, locator, heading, text, "
                "source_locator) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    sequence,
                    locator,
                    f"Synthetic heading {index}",
                    f"Synthetic segment {index}",
                    locator,
                ),
            )
            code = f"Z98Z{index:04d}/01"
            concept_id = int(
                connection.execute(
                    "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                    "concept_type, record_status, source_file_id, source_locator) "
                    "VALUES (?, 'fi', '', ?, ?, 'document_fixture', 'reference_only', ?, ?)",
                    (release_id, code, code, source_file_id, locator),
                ).lastrowid
            )
            connection.execute(
                "INSERT INTO document_link(document_id, concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'document_fixture', ?, ?)",
                (document_id, concept_id, source_file_id, locator),
            )
        connection.commit()
    finally:
        connection.close()
    return document_id, max_sequence


def test_document_segments_and_related_classifications_are_independently_paginated(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "paged-document.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, max_sequence = _seed_large_document(database)
    store = PMGSStore.open(database)

    first = store.get_document(
        document_id,
        segment_limit=50,
        related_classification_limit=50,
    )
    second = store.get_document(
        document_id,
        segment_limit=50,
        segment_offset=50,
        related_classification_limit=50,
        related_classification_offset=50,
    )

    assert first["segment_limit"] == 50
    assert first["segment_offset"] == 0
    assert first["segments_truncated"] is True
    assert first["next_segment_offset"] == 50
    assert second["segment_offset"] == 50
    assert {
        item["sequence_number"]
        for item in first["segments"]  # type: ignore[index]
    }.isdisjoint(
        {item["sequence_number"] for item in second["segments"]}  # type: ignore[index]
    )

    assert first["related_classification_limit"] == 50
    assert first["related_classification_offset"] == 0
    assert first["related_classifications_truncated"] is True
    assert first["next_related_classification_offset"] == 50
    assert second["related_classification_offset"] == 50
    assert {
        item["code"]
        for item in first["related_classifications"]  # type: ignore[index]
    }.isdisjoint(
        {item["code"] for item in second["related_classifications"]}  # type: ignore[index]
    )

    by_section = store.get_document(document_id, section=max_sequence + 1)
    by_locator = store.get_document(document_id, locator="synthetic-section:1")
    assert by_section["segments"] == by_locator["segments"]
    assert by_section["selector"] == {
        "page": None,
        "section": max_sequence + 1,
        "locator": None,
    }


def test_document_selectors_are_mutually_exclusive_and_not_found_is_structured(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "document-selectors.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, max_sequence = _seed_large_document(database)
    store = PMGSStore.open(database)

    with pytest.raises(PMGSQueryError) as conflicting:
        store.get_document(document_id, section=max_sequence + 1, locator="synthetic-section:1")
    assert conflicting.value.code == "INVALID_DOCUMENT_SELECTOR"

    with pytest.raises(PMGSQueryError) as missing:
        store.get_document(document_id, section=999_999)
    assert missing.value.code == "DOCUMENT_SELECTOR_NOT_FOUND"


@pytest.mark.anyio
async def test_cli_and_mcp_expose_the_same_document_selector_and_page_contract(
    synthetic_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "document-interfaces.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, max_sequence = _seed_large_document(database)

    exit_code = main(
        [
            "document",
            document_id,
            "--db",
            str(database),
            "--section",
            str(max_sequence + 1),
            "--segment-limit",
            "1",
            "--related-classification-limit",
            "1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["selector"]["section"] == max_sequence + 1
    assert payload["segment_limit"] == 1
    assert payload["related_classification_limit"] == 1

    server = create_server(database)
    tools = await server.list_tools()
    document_schema = next(tool for tool in tools if tool.name == "get_pmgs_document").input_schema
    properties = document_schema["properties"]
    assert properties["section"]["anyOf"][0]["minimum"] == 1
    assert properties["segment_limit"]["maximum"] == 200
    assert properties["related_classification_limit"]["maximum"] == 200

    result = await server.call_tool(
        "get_pmgs_document",
        {
            "document_id": document_id,
            "section": max_sequence + 1,
            "segment_limit": 1,
            "related_classification_limit": 1,
        },
    )
    assert result.structured_content is not None
    assert result.structured_content["selector"]["section"] == max_sequence + 1
