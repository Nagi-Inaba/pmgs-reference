from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference import PMGSQueryError, PMGSStore


def _seed_children(database: Path, count: int = 805) -> None:
    connection = sqlite3.connect(database)
    try:
        release_id = str(connection.execute("SELECT release_id FROM release LIMIT 1").fetchone()[0])
        source_file_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        parent_id = int(
            connection.execute(
                "SELECT concept_id FROM concept WHERE scheme = 'fi' "
                "AND normalized_code = 'G06F' LIMIT 1"
            ).fetchone()[0]
        )
        for index in range(count):
            code = f"Z97Z{index:04d}/01"
            child_id = int(
                connection.execute(
                    "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                    "concept_type, record_status, source_file_id, source_locator) "
                    "VALUES (?, 'fi', '', ?, ?, 'hierarchy_fixture', 'canonical', ?, ?)",
                    (release_id, code, code, source_file_id, f"hierarchy:{index}"),
                ).lastrowid
            )
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, source_file_id, "
                "source_locator) VALUES (?, '', ?, ?)",
                (child_id, source_file_id, f"hierarchy:{index}"),
            )
            connection.execute(
                "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'parent', ?, ?)",
                (child_id, parent_id, source_file_id, f"hierarchy:{index}"),
            )
        connection.commit()
    finally:
        connection.close()


def _add_overlapping_active_revision(database: Path) -> None:
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT c.concept_id, cr.source_file_id FROM concept c "
            "JOIN concept_revision cr ON cr.concept_id = c.concept_id "
            "WHERE c.scheme = 'fi' AND c.normalized_code = 'G06F3/048' "
            "ORDER BY cr.revision_id LIMIT 1"
        ).fetchone()
        assert row is not None
        connection.execute(
            "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, valid_to, "
            "source_file_id, source_locator) VALUES (?, '2099.02', NULL, NULL, ?, ?)",
            (int(row[0]), int(row[1]), "hierarchy:overlapping-active-revision"),
        )
        connection.commit()
    finally:
        connection.close()


def test_hierarchy_returns_bounded_summaries_without_n_plus_one_lookup(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "hierarchy.sqlite"
    shutil.copy2(synthetic_database, database)
    _seed_children(database)
    store = PMGSStore.open(database)

    store.lookup = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("hierarchy pagination must not call lookup per result")
    )
    first = store.hierarchy("children", "fi", "G06F", limit=200, offset=0)
    second = store.hierarchy("children", "fi", "G06F", limit=200, offset=200)

    assert first["direction"] == "children"
    assert first["count"] >= 805
    assert first["limit"] == 200
    assert first["offset"] == 0
    assert first["truncated"] is True
    assert first["next_offset"] == 200
    assert len(first["results"]) == 200
    assert len(second["results"]) == 200
    assert {item["code"] for item in first["results"]}.isdisjoint(
        {item["code"] for item in second["results"]}
    )
    # record_status is part of the documented bounded-summary contract.
    allowed = {"scheme", "edition", "code", "version", "label", "record_status"}
    assert all(set(item) <= allowed for item in first["results"])


def test_hierarchy_rejects_multiple_active_revisions(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "hierarchy-overlap.sqlite"
    shutil.copy2(synthetic_database, database)
    _add_overlapping_active_revision(database)

    with pytest.raises(PMGSQueryError) as error:
        PMGSStore.open(database).hierarchy("children", "fi", "G06F", limit=20)

    assert error.value.code == "MULTIPLE_ACTIVE_REVISIONS"


def test_existing_parents_and_children_wrappers_preserve_compatibility(
    synthetic_database: Path,
) -> None:
    store = PMGSStore.open(synthetic_database)

    parent_page = store.hierarchy("parents", "fi", "G06F3/048", limit=20, offset=0)
    child_page = store.hierarchy("children", "fi", "G06F", limit=20, offset=0)

    assert {item["code"] for item in parent_page["results"]} == {
        item["code"] for item in store.parents("fi", "G06F3/048")
    }
    assert {item["code"] for item in child_page["results"]} == {
        item["code"] for item in store.children("fi", "G06F")
    }
