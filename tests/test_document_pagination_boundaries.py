from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference import PMGSStore


def _extend_document_to_counts(
    database: Path,
    *,
    segment_target: int,
    related_target: int,
) -> str:
    with sqlite3.connect(database) as connection:
        document_id = str(
            connection.execute(
                "SELECT d.document_id FROM document d "
                "JOIN document_text dt ON dt.document_id = d.document_id "
                "GROUP BY d.document_id ORDER BY d.document_id LIMIT 1"
            ).fetchone()[0]
        )
        release_id = str(connection.execute("SELECT release_id FROM release LIMIT 1").fetchone()[0])
        source_file_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        max_sequence = int(
            connection.execute(
                "SELECT MAX(sequence_number) FROM document_text WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
        )
        segment_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM document_text WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0]
        )
        related_count = int(
            connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM document_link WHERE document_id = ?) + "
                "(SELECT COUNT(*) FROM document_revision_link WHERE document_id = ?)",
                (document_id, document_id),
            ).fetchone()[0]
        )
        if segment_count > segment_target or related_count > related_target:
            pytest.skip("synthetic fixture already exceeds the requested pagination boundary")

        for index in range(segment_target - segment_count):
            sequence = max_sequence + index + 1
            locator = f"boundary-segment:{segment_target}:{index}"
            connection.execute(
                "INSERT INTO document_text(document_id, sequence_number, locator, heading, text, "
                "source_locator) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    sequence,
                    locator,
                    f"Boundary heading {index}",
                    f"Boundary segment {index}",
                    locator,
                ),
            )

        for index in range(related_target - related_count):
            locator = f"boundary-related:{related_target}:{index}"
            code = f"Z97Z{related_target:03d}{index:04d}/01"
            concept_id = int(
                connection.execute(
                    "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                    "concept_type, record_status, source_file_id, source_locator) "
                    "VALUES (?, 'fi', '', ?, ?, 'document_boundary', 'reference_only', ?, ?)",
                    (release_id, code, code, source_file_id, locator),
                ).lastrowid
            )
            connection.execute(
                "INSERT INTO document_link(document_id, concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'document_boundary', ?, ?)",
                (document_id, concept_id, source_file_id, locator),
            )
        connection.commit()
    return document_id


@pytest.mark.parametrize("target", [200, 201])
def test_exact_200_and_201_item_boundaries(
    synthetic_database: Path,
    tmp_path: Path,
    target: int,
) -> None:
    database = tmp_path / f"document-boundary-{target}.sqlite"
    shutil.copy2(synthetic_database, database)
    document_id = _extend_document_to_counts(
        database,
        segment_target=target,
        related_target=target,
    )
    store = PMGSStore.open(database)

    first = store.get_document(
        document_id,
        segment_limit=200,
        related_classification_limit=200,
    )
    assert first["segment_count"] == target
    assert len(first["segments"]) == 200
    assert first["segments_truncated"] is (target == 201)
    assert first["next_segment_offset"] == (200 if target == 201 else None)
    assert first["related_classification_count"] == target
    assert len(first["related_classifications"]) == 200
    assert first["related_classifications_truncated"] is (target == 201)
    assert first["next_related_classification_offset"] == (200 if target == 201 else None)

    if target == 201:
        final = store.get_document(
            document_id,
            segment_limit=200,
            segment_offset=200,
            related_classification_limit=200,
            related_classification_offset=200,
        )
        assert len(final["segments"]) == 1
        assert final["segments_truncated"] is False
        assert final["next_segment_offset"] is None
        assert len(final["related_classifications"]) == 1
        assert final["related_classifications_truncated"] is False
        assert final["next_related_classification_offset"] is None

        exhausted = store.get_document(
            document_id,
            segment_limit=200,
            segment_offset=201,
            related_classification_limit=200,
            related_classification_offset=201,
        )
        assert exhausted["segments"] == []
        assert exhausted["segments_truncated"] is False
        assert exhausted["next_segment_offset"] is None
        assert exhausted["related_classifications"] == []
        assert exhausted["related_classifications_truncated"] is False
        assert exhausted["next_related_classification_offset"] is None
