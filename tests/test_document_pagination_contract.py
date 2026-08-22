from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from pmgs_reference import PMGSQueryError, PMGSStore
from pmgs_reference.cli import main
from pmgs_reference.mcp_server import create_server
from pmgs_reference.store_types import JSONDict


def _seed_large_document(database: Path) -> tuple[str, int, str, str, int]:
    store = PMGSStore.open(database)
    document_id = str(store.related_documents("fi", "G06F3/048")[0]["document_id"])
    connection = sqlite3.connect(database)
    try:
        source_file_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        release_id = str(connection.execute("SELECT release_id FROM release LIMIT 1").fetchone()[0])
        maximum = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) FROM document_text WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
        )
        canonical_sequence = maximum + 1
        canonical_locator = "section:canonical"
        canonical_heading = "Canonical synthetic section"
        connection.execute(
            "INSERT INTO document_text(document_id, sequence_number, locator, heading, text, "
            "source_locator) VALUES (?, ?, ?, ?, 'Canonical document segment', ?)",
            (
                document_id,
                canonical_sequence,
                canonical_locator,
                canonical_heading,
                canonical_locator,
            ),
        )
        for index in range(1, 206):
            sequence = canonical_sequence + index
            locator = f"section:page-{index:03d}"
            connection.execute(
                "INSERT INTO document_text(document_id, sequence_number, locator, heading, text, "
                "source_locator) VALUES (?, ?, ?, NULL, ?, ?)",
                (
                    document_id,
                    sequence,
                    locator,
                    f"Paged document segment {index}",
                    locator,
                ),
            )

        for index in range(205):
            code = f"Z98A{index:04d}/99"
            concept_id = int(
                connection.execute(
                    "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                    "concept_type, record_status, source_file_id, source_locator) "
                    "VALUES (?, 'fi', '', ?, ?, 'document_fixture', 'reference_only', ?, ?)",
                    (release_id, code, code, source_file_id, f"document-related:{index}"),
                ).lastrowid
            )
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, valid_to, "
                "level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '', NULL, NULL, NULL, ?, ?, ?)",
                (concept_id, index + 1, source_file_id, f"document-related:{index}"),
            )
            connection.execute(
                "INSERT INTO document_link(document_id, concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'synthetic_document_relation', ?, ?)",
                (document_id, concept_id, source_file_id, f"document-related:{index}"),
            )
        connection.commit()
        total_segments = int(
            connection.execute(
                "SELECT COUNT(*) FROM document_text WHERE document_id = ?", (document_id,)
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return (
        document_id,
        canonical_sequence,
        canonical_locator,
        canonical_heading,
        total_segments,
    )


def test_document_selectors_share_one_sequence_contract_and_keep_literal_selectors(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "document-selectors.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, sequence, locator, heading, _ = _seed_large_document(database)
    store = PMGSStore.open(database)

    by_section = store.get_document(document_id, section=sequence)
    by_locator = store.get_document(document_id, locator=locator)
    by_heading = store.get_document(document_id, heading=heading)

    assert [item["sequence_number"] for item in by_section["segments"]] == [sequence]  # type: ignore[index]
    assert [item["sequence_number"] for item in by_locator["segments"]] == [sequence]  # type: ignore[index]
    assert [item["sequence_number"] for item in by_heading["segments"]] == [sequence]  # type: ignore[index]
    with pytest.raises(PMGSQueryError, match="positive integer"):
        store.get_document(document_id, section=cast(int, "section:canonical"))
    with pytest.raises(PMGSQueryError, match="mutually exclusive"):
        store.get_document(document_id, page=1, section=sequence)


def test_document_segments_and_related_classifications_are_recoverably_paginated(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "document-pages.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, _, _, _, total_segments = _seed_large_document(database)
    store = PMGSStore.open(database)

    first = store.get_document(
        document_id,
        segment_limit=200,
        related_classification_limit=200,
    )
    second = store.get_document(
        document_id,
        segment_limit=200,
        segment_offset=200,
        related_classification_limit=200,
        related_classification_offset=200,
    )

    assert first["segment_count"] == total_segments
    assert first["segment_limit"] == 200
    assert first["segment_offset"] == 0
    assert first["segments_truncated"] is True
    assert first["next_segment_offset"] == 200
    assert second["segment_offset"] == 200
    assert second["segments_truncated"] is False
    assert second["next_segment_offset"] is None
    assert len(first["segments"]) == 200
    assert len(first["segments"]) + len(second["segments"]) == total_segments
    first_sequences = {item["sequence_number"] for item in first["segments"]}  # type: ignore[union-attr]
    second_sequences = {item["sequence_number"] for item in second["segments"]}  # type: ignore[union-attr]
    assert first_sequences.isdisjoint(second_sequences)

    assert int(first["related_classification_count"]) >= 205
    assert first["related_classification_limit"] == 200
    assert first["related_classification_offset"] == 0
    assert first["related_classifications_truncated"] is True
    assert first["next_related_classification_offset"] == 200
    assert second["related_classification_offset"] == 200
    assert second["related_classifications_truncated"] is False
    assert second["next_related_classification_offset"] is None
    first_related = {
        (item["scheme"], item["edition"], item["code"], item["version"], item["type"])
        for item in first["related_classifications"]  # type: ignore[union-attr]
    }
    second_related = {
        (item["scheme"], item["edition"], item["code"], item["version"], item["type"])
        for item in second["related_classifications"]  # type: ignore[union-attr]
    }
    assert first_related.isdisjoint(second_related)
    assert len(first_related | second_related) == first["related_classification_count"]


def test_cli_and_mcp_expose_the_same_document_page_controls(
    synthetic_database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "document-clients.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id, sequence, _, _, _ = _seed_large_document(database)

    result = main(
        [
            "document",
            document_id,
            "--db",
            str(database),
            "--section",
            str(sequence),
            "--segment-limit",
            "1",
            "--related-classification-limit",
            "1",
            "--json",
        ]
    )
    cli_payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert cli_payload["selector"]["section"] == sequence
    assert cli_payload["segment_limit"] == 1
    assert cli_payload["related_classification_limit"] == 1

    server = create_server(database)
    response = asyncio.run(
        server.call_tool(
            "get_pmgs_document",
            {
                "document_id": document_id,
                "section": sequence,
                "segment_limit": 1,
                "related_classification_limit": 1,
            },
        )
    )
    assert response.is_error is not True
    mcp_payload = cast(JSONDict, response.structured_content or {})
    assert mcp_payload["selector"] == cli_payload["selector"]
    assert mcp_payload["segments"] == cli_payload["segments"]
