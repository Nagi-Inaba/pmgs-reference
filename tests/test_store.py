from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import pmgs_reference.data_paths as data_paths_module
import pmgs_reference.store as store_module
from pmgs_reference import PMGSQueryError, PMGSStore
from pmgs_reference.errors import DocumentNotFoundError, EditionNotFoundError
from pmgs_reference.validation import validate_database


def _classification_schema() -> dict[str, object]:
    path = Path(__file__).parents[1] / "schemas" / "classification-record.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_open_lookup_and_database_discovery(
    synthetic_database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = PMGSStore.open(synthetic_database)
    exact = explicit.lookup("fi", "G06F3/048")
    normalized = explicit.lookup("fterm", "4c083 aa01", language="en")

    assert exact["match_status"] == "exact"
    assert exact["code"] == "G06F3/048"
    assert any(text["kind"] == "fi_handbook" for text in exact["texts"])  # type: ignore[index]
    assert any(document["kind"] == "fi_handbook" for document in exact["documents"])  # type: ignore[index]
    assert normalized["match_status"] == "normalized_exact"
    assert normalized["normalized_code"] == "4C083AA01"
    assert any(item["name"] == "fi_scope" for item in normalized["properties"])  # type: ignore[index]
    Draft202012Validator(_classification_schema(), format_checker=FormatChecker()).validate(exact)
    serialized = json.dumps(exact, ensure_ascii=False)
    assert str(synthetic_database.parent) not in serialized

    monkeypatch.setenv("PMGS_REFERENCE_DB", str(synthetic_database))
    assert PMGSStore.open().release_info()["release_id"] == "JPPM2099001"

    monkeypatch.delenv("PMGS_REFERENCE_DB")
    default_database = tmp_path / "pmgs-reference" / "data" / "current.sqlite"
    default_database.parent.mkdir(parents=True)
    shutil.copy2(synthetic_database, default_database)
    monkeypatch.setattr(data_paths_module, "default_data_root", lambda: tmp_path / "pmgs-reference")
    assert PMGSStore.open().release_info()["source_file_count"] == 26


def test_open_resolves_an_explicit_data_directory_before_the_environment(
    synthetic_database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "managed"
    release = PMGSStore.open(synthetic_database).release_info()
    validation = validate_database(synthetic_database)
    managed = (
        data_root
        / "data"
        / "releases"
        / str(release["release_id"])
        / str(release["source_manifest_sha256"])
        / f"{validation.database_sha256}.sqlite"
    )
    managed.parent.mkdir(parents=True)
    shutil.copy2(synthetic_database, managed)
    state = data_root / "state"
    state.mkdir()
    (state / "current.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "release_id": "JPPM2099001",
                "source_manifest_sha256": release["source_manifest_sha256"],
                "database_sha256": validation.database_sha256,
                "database_schema_version": validation.user_version,
                "database_relpath": managed.relative_to(data_root).as_posix(),
                "activated_at": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PMGS_REFERENCE_DB", str(tmp_path / "missing.sqlite"))

    store = PMGSStore.open(data_dir=data_root)

    assert store.path == managed.resolve()


def test_managed_pointer_metadata_must_match_the_database(
    synthetic_database: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "managed"
    release = PMGSStore.open(synthetic_database).release_info()
    validation = validate_database(synthetic_database)
    managed = (
        data_root
        / "data"
        / "releases"
        / "JPPM2099002"
        / str(release["source_manifest_sha256"])
        / f"{validation.database_sha256}.sqlite"
    )
    managed.parent.mkdir(parents=True)
    shutil.copy2(synthetic_database, managed)
    state = data_root / "state"
    state.mkdir()
    (state / "current.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "release_id": "JPPM2099002",
                "source_manifest_sha256": release["source_manifest_sha256"],
                "database_sha256": validation.database_sha256,
                "database_schema_version": validation.user_version,
                "database_relpath": managed.relative_to(data_root).as_posix(),
                "activated_at": "2099-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="identity does not match"):
        PMGSStore.open(data_dir=data_root)


def test_invalid_current_pointer_fails_closed_without_legacy_fallback(
    synthetic_database: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "managed"
    legacy = data_root / "data" / "current.sqlite"
    legacy.parent.mkdir(parents=True)
    shutil.copy2(synthetic_database, legacy)
    state = data_root / "state"
    state.mkdir()
    (state / "current.json").write_text(
        json.dumps({"schema_version": "1.0", "database_relpath": "../../outside.sqlite"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"current\.json"):
        PMGSStore.open(data_dir=data_root)


def test_lookup_preserves_scheme_and_edition_identity(synthetic_database: Path) -> None:
    store = PMGSStore.open(synthetic_database)

    current_ipc = store.lookup("ipc", "G06F3/048")
    legacy_revision = store.lookup("ipc", "G06F3/048", version="(2006.01)")
    missing_revision = store.lookup("ipc", "G06F3/048", version="2099.01")
    expired = store.lookup("ipc", "G06F3/050")
    legacy_ipc = store.lookup("ipc", "G06F3/048", edition="4")
    missing = store.lookup("fi", "Z99Z99/999")

    assert current_ipc["edition"] == "8U"
    assert current_ipc["schema_version"] == "2.0"
    assert current_ipc["reference_date"] == "2026-01-01"
    assert current_ipc["version"] == "2021.01"
    assert current_ipc["valid_from"] == "2021-01-01"
    assert current_ipc["valid_to"] == "9999-12-31"
    assert all("legacy" not in str(item["text"]) for item in current_ipc["texts"])  # type: ignore[index]
    assert legacy_revision["version"] == "2006.01"
    assert any("legacy" in str(item["text"]) for item in legacy_revision["texts"])  # type: ignore[index]
    assert missing_revision["match_status"] == "version_not_found"
    assert missing_revision["sources"]
    assert {item["version"] for item in missing_revision["available_versions"]} == {  # type: ignore[index]
        "2006.01",
        "2021.01",
    }
    assert expired["match_status"] == "not_valid_at_release"
    assert expired["texts"] == []
    assert expired["sources"]
    assert legacy_ipc["edition"] == "4"
    assert current_ipc["texts"] != legacy_ipc["texts"]
    assert missing["match_status"] == "not_found"
    assert missing["sources"] == []
    assert missing["labels"] == []
    assert missing["properties"] == []
    assert missing["documents"] == []

    with pytest.raises(EditionNotFoundError, match="9Z"):
        store.lookup("ipc", "G06F3/048", edition="9Z")
    with pytest.raises(PMGSQueryError, match="only for IPC"):
        store.lookup("fi", "G06F3/048", edition="8U")
    with pytest.raises(PMGSQueryError, match="only for IPC"):
        store.lookup("fi", "G06F3/048", version="2021.01")


def test_lookup_returns_reference_only_fi_with_lineage_and_paged_relations(
    synthetic_database: Path,
) -> None:
    store = PMGSStore.open(synthetic_database)

    record = store.lookup("fi", "G06F3/040", relation_limit=1)

    assert record["record_status"] == "reference_only"
    assert record["match_status"] == "exact"
    assert record["relation_count"] >= 1  # type: ignore[operator]
    assert len(record["relations"]) == 1
    assert record["relations_truncated"] is (
        int(record["relation_count"]) > len(record["relations"])
    )
    assert record["relations"][0]["code"] == "G06F3/041"  # type: ignore[index]
    assert any(item["kind"] == "fi_amendment" for item in record["documents"])  # type: ignore[index]
    assert all(item["attribution"] == "Copyright (C) TEST 2026" for item in record["sources"])  # type: ignore[index]

    next_offset = record["next_relation_offset"]
    if next_offset is not None:
        second = store.lookup("fi", "G06F3/040", relation_limit=1, relation_offset=int(next_offset))
        assert second["relations"] != record["relations"]


def test_lookup_pages_more_than_800_synthetic_relations_without_loss(
    synthetic_database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "many-relations.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        source_id = int(connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0])
        origin_id = int(
            connection.execute(
                "SELECT concept_id FROM concept WHERE scheme = 'fi' "
                "AND normalized_code = 'G06F3/048'"
            ).fetchone()[0]
        )
        for index in range(805):
            code = f"Z99Z{index:04d}/99"
            cursor = connection.execute(
                "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                "concept_type, record_status, source_file_id, source_locator) "
                "VALUES ('JPPM2099001', 'fi', '', ?, ?, 'synthetic_reference', "
                "'reference_only', ?, ?)",
                (code, code, source_id, f"synthetic-relation:{index}"),
            )
            target_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, "
                "valid_to, level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '', NULL, NULL, NULL, ?, ?, ?)",
                (target_id, index, source_id, f"synthetic-relation:{index}"),
            )
            connection.execute(
                "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'synthetic_paging', ?, ?)",
                (origin_id, target_id, source_id, f"synthetic-relation:{index}"),
            )
        connection.commit()
    finally:
        connection.close()

    store = PMGSStore.open(database)
    traced_connection = sqlite3.connect(database)
    traced_connection.row_factory = sqlite3.Row
    traced_queries: list[str] = []
    traced_connection.set_trace_callback(traced_queries.append)
    monkeypatch.setattr(store, "_connect", lambda: traced_connection)
    offset = 0
    collected: list[tuple[object, ...]] = []
    relation_count: int | None = None
    while True:
        page = store.lookup("fi", "G06F3/048", relation_limit=200, relation_offset=offset)
        current_count = int(page["relation_count"])
        relation_count = current_count if relation_count is None else relation_count
        assert current_count == relation_count
        for item in page["relations"]:  # type: ignore[union-attr]
            collected.append(
                (
                    item["type"],
                    item["scheme"],
                    item["edition"],
                    item["code"],
                    item["version"],
                    item["source_id"],
                    item["locator"],
                )
            )
        next_offset = page["next_relation_offset"]
        if next_offset is None:
            assert page["relations_truncated"] is (offset > 0)
            break
        assert page["relations_truncated"] is True
        offset = int(next_offset)

    assert relation_count is not None and relation_count > 800
    assert len(collected) == relation_count
    assert len(set(collected)) == relation_count
    relation_queries = [query for query in traced_queries if "relation_candidates" in query]
    assert relation_queries
    assert any("LIMIT 200 OFFSET" in query for query in relation_queries)
    traced_connection.close()


def test_children_reads_every_relation_page(synthetic_database: Path, tmp_path: Path) -> None:
    database = tmp_path / "many-children.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        source_id = int(connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0])
        parent_id = int(
            connection.execute(
                "SELECT concept_id FROM concept WHERE scheme = 'fi' AND normalized_code = 'G06F'"
            ).fetchone()[0]
        )
        expected = {"G06F3/048"}
        for index in range(55):
            code = f"G06F9/{index:03d}"
            expected.add(code)
            cursor = connection.execute(
                "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                "concept_type, record_status, source_file_id, source_locator) "
                "VALUES ('JPPM2099001', 'fi', '', ?, ?, 'synthetic_child', "
                "'canonical', ?, ?)",
                (code, code, source_id, f"synthetic-child:{index}"),
            )
            child_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, "
                "valid_to, level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '', NULL, NULL, NULL, ?, ?, ?)",
                (child_id, index, source_id, f"synthetic-child:{index}"),
            )
            connection.execute(
                "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'parent', ?, ?)",
                (child_id, parent_id, source_id, f"synthetic-child:{index}"),
            )
        connection.commit()
    finally:
        connection.close()

    children = PMGSStore.open(database).children("fi", "G06F")

    assert {str(child["code"]) for child in children} == expected


def test_relation_sources_are_bounded_to_the_current_page(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "relation-source-pages.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        template = connection.execute(
            "SELECT release_id, size_bytes, sha256, file_type, encoding, data_group, parser, "
            "status FROM source_file ORDER BY file_id LIMIT 1"
        ).fetchone()
        origin_id = int(
            connection.execute(
                "SELECT concept_id FROM concept WHERE scheme = 'fi' "
                "AND normalized_code = 'G06F3/048'"
            ).fetchone()[0]
        )
        for index in range(3):
            source_id = f"synthetic-page-source-{index}"
            cursor = connection.execute(
                "INSERT INTO source_file(release_id, source_id, relative_path, size_bytes, "
                "sha256, file_type, encoding, data_group, parser, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *template[:1],
                    source_id,
                    f"synthetic/page-source-{index}.csv",
                    *template[1:],
                ),
            )
            source_file_id = int(cursor.lastrowid)
            code = f"Z99Y{index:04d}/99"
            cursor = connection.execute(
                "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                "concept_type, record_status, source_file_id, source_locator) "
                "VALUES ('JPPM2099001', 'fi', '', ?, ?, 'synthetic_reference', "
                "'reference_only', ?, ?)",
                (code, code, source_file_id, f"page-source:{index}"),
            )
            target_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, "
                "valid_to, level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '', NULL, NULL, NULL, ?, ?, ?)",
                (target_id, index, source_file_id, f"page-source:{index}"),
            )
            connection.execute(
                "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'zz_page_source', ?, ?)",
                (origin_id, target_id, source_file_id, f"page-source:{index}"),
            )
        connection.commit()
    finally:
        connection.close()

    store = PMGSStore.open(database)
    first = store.lookup("fi", "G06F3/048", relation_limit=1)
    second = store.lookup(
        "fi",
        "G06F3/048",
        relation_limit=1,
        relation_offset=int(first["next_relation_offset"]),
    )

    first_relation = first["relations"][0]  # type: ignore[index]
    second_relation = second["relations"][0]  # type: ignore[index]
    first_sources = {item["source_id"] for item in first["sources"]}  # type: ignore[union-attr]
    second_sources = {item["source_id"] for item in second["sources"]}  # type: ignore[union-attr]
    assert first_relation["source_id"] in first_sources
    assert second_relation["source_id"] in second_sources
    assert second_relation["source_id"] not in first_sources


def test_lookup_deduplicates_relations_with_deterministic_minimum_lineage(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "duplicate-relations.sqlite"
    shutil.copy2(synthetic_database, database)
    connection = sqlite3.connect(database)
    try:
        low_source_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        high_source_id = int(
            connection.execute("SELECT MAX(file_id) FROM source_file").fetchone()[0]
        )
        expected_source = str(
            connection.execute(
                "SELECT source_id FROM source_file WHERE file_id = ?", (low_source_id,)
            ).fetchone()[0]
        )
        origin_id = int(
            connection.execute(
                "SELECT concept_id FROM concept WHERE scheme = 'fi' "
                "AND normalized_code = 'G06F3/048'"
            ).fetchone()[0]
        )
        origin_revision_id = int(
            connection.execute(
                "SELECT revision_id FROM concept_revision WHERE concept_id = ?", (origin_id,)
            ).fetchone()[0]
        )
        cursor = connection.execute(
            "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
            "concept_type, record_status, source_file_id, source_locator) "
            "VALUES ('JPPM2099001', 'fi', '', 'Z99Z9999/99', 'Z99Z9999/99', "
            "'synthetic_reference', 'reference_only', ?, 'duplicate-target')",
            (low_source_id,),
        )
        target_id = int(cursor.lastrowid)
        cursor = connection.execute(
            "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, valid_to, "
            "level, sequence_number, source_file_id, source_locator) "
            "VALUES (?, '', NULL, NULL, NULL, 1, ?, 'duplicate-target')",
            (target_id, low_source_id),
        )
        target_revision_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
            "source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'z-concept')",
            (origin_id, target_id, high_source_id),
        )
        connection.execute(
            "INSERT INTO revision_relation(from_revision_id, to_revision_id, kind, "
            "source_file_id, source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'z-revision')",
            (origin_revision_id, target_revision_id, low_source_id),
        )
        connection.execute(
            "INSERT INTO revision_relation(from_revision_id, to_revision_id, kind, "
            "source_file_id, source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'a-revision')",
            (target_revision_id, origin_revision_id, low_source_id),
        )
        connection.commit()
    finally:
        connection.close()

    record = PMGSStore.open(database).lookup("fi", "G06F3/048", relation_limit=200)
    duplicate = [
        item
        for item in record["relations"]  # type: ignore[union-attr]
        if item["type"] == "duplicate_lineage"
    ]

    assert len(duplicate) == 1
    assert duplicate[0]["source_id"] == expected_source
    assert duplicate[0]["locator"] == "a-revision"


def test_lookup_and_get_document_fail_closed_when_serialized_response_is_too_large(
    synthetic_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PMGSStore.open(synthetic_database)
    document_id = str(store.related_documents("fi", "G06F3/048")[0]["document_id"])
    assert store_module._MAX_STRUCTURED_RESPONSE_BYTES == 4 * 1024 * 1024
    monkeypatch.setattr(store_module, "_MAX_STRUCTURED_RESPONSE_BYTES", 1)

    for operation in (
        lambda: store.lookup("fi", "G06F3/048"),
        lambda: store.get_document(document_id),
    ):
        with pytest.raises(PMGSQueryError) as error:
            operation()
        assert error.value.code == "RESPONSE_TOO_LARGE"


def test_labels_carry_source_lineage_and_composite_search_keeps_each_content_type(
    synthetic_database: Path,
) -> None:
    store = PMGSStore.open(synthetic_database)
    classification = store.lookup("fterm", "4C083AA01")
    combined = store.search_pmgs("Synthetic", limit=1)

    assert classification["labels"]
    assert all(label["kind"] == "label" for label in classification["labels"])  # type: ignore[index]
    assert all(label["source_id"] and label["locator"] for label in classification["labels"])  # type: ignore[index]
    assert combined["results_by_type"]["classification"]["count"] == 1  # type: ignore[index]
    assert combined["results_by_type"]["document"]["count"] == 1  # type: ignore[index]
    assert combined["results_by_type"]["classification"]["requested"] is True  # type: ignore[index]
    assert combined["results_by_type"]["document"]["requested"] is True  # type: ignore[index]

    reference_search = store.search("reference-only source", schemes=["fi"])
    assert all(item["code"] != "G06F3/040" for item in reference_search["results"])  # type: ignore[index]


def test_lexical_search_hierarchy_and_documents(synthetic_database: Path) -> None:
    store = PMGSStore.open(synthetic_database)

    classification_hits = store.search("Synthetic interaction", schemes=["fi"], limit=5)
    japanese_substring_hits = store.search("相互作用技術", schemes=["fi"], limit=5)
    short_substring_hits = store.search("相互", schemes=["fi"], limit=5)
    document_hits = store.search_documents("Synthetic handbook", limit=5)
    parents = store.parents("fi", "G06F3/048")
    children = store.children("fi", "G06F")
    related = store.related_documents("fi", "G06F3/048")

    assert classification_hits["search_mode"] == "sqlite_fts5_trigram_lexical"
    assert classification_hits["count"] == 1
    assert classification_hits["results"][0]["code"] == "G06F3/048"  # type: ignore[index]
    assert japanese_substring_hits["count"] == 1
    assert japanese_substring_hits["results"][0]["code"] == "G06F3/048"  # type: ignore[index]
    assert short_substring_hits["search_mode"] == "sqlite_literal_substring_lexical"
    assert short_substring_hits["count"] == 1
    assert document_hits["count"] >= 1  # type: ignore[operator]
    assert any(parent["code"] == "G06F" for parent in parents)
    assert any(child["code"] == "G06F3/048" for child in children)
    assert any(item["kind"] == "fi_handbook" for item in related)

    document_id = str(related[0]["document_id"])
    document = store.get_document(document_id)
    assert document["document_id"] == document_id
    assert document["segment_count"] >= 1  # type: ignore[operator]
    assert document["source"]["relative_id"]  # type: ignore[index]


def test_pdf_page_release_info_and_safe_errors(synthetic_database: Path) -> None:
    store = PMGSStore.open(synthetic_database)
    related = store.related_documents("ipc", "G06F3/048", edition="8U")
    definition = next(item for item in related if item["kind"] == "ipc_definition")
    page = store.get_document(str(definition["document_id"]), page=1)
    info = store.release_info()

    assert page["segments"][0]["locator"] == "page:1"  # type: ignore[index]
    assert "Synthetic IPC definition" in page["segments"][0]["text"]  # type: ignore[index]
    assert info["release_id"] == "JPPM2099001"
    assert info["source_manifest_sha256"]
    assert info["reference_date"] == "2026-01-01"
    assert info["source"]["attribution"] == "Copyright (C) TEST 2026"  # type: ignore[index]

    with pytest.raises(DocumentNotFoundError) as missing:
        store.get_document("doc-not-present")
    assert missing.value.as_dict()["code"] == "DOCUMENT_NOT_FOUND"
    with pytest.raises(PMGSQueryError, match="1 to 500"):
        store.search("")
    with pytest.raises(PMGSQueryError, match="between 1 and 100"):
        store.search("Synthetic", limit=101)
    with pytest.raises(PMGSQueryError, match=r"YYYY\.MM"):
        store.lookup("ipc", "G06F3/048", version="2021")
    with pytest.raises(PMGSQueryError, match="between 1 and 200"):
        store.lookup("fi", "G06F3/048", relation_limit=201)


def test_open_rejects_schema_v1_with_upgrade_error(
    synthetic_database: Path, tmp_path: Path
) -> None:
    legacy = tmp_path / "legacy.sqlite"
    shutil.copy2(synthetic_database, legacy)
    connection = sqlite3.connect(legacy)
    try:
        connection.execute("PRAGMA user_version = 1")
    finally:
        connection.close()

    with pytest.raises(PMGSQueryError) as error:
        PMGSStore.open(legacy)

    assert error.value.code == "DATABASE_SCHEMA_UPGRADE_REQUIRED"
