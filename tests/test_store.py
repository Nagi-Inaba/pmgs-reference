from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import pmgs_reference.data_paths as data_paths_module
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
    legacy_ipc = store.lookup("ipc", "G06F3/048", edition="4")
    missing = store.lookup("fi", "Z99Z99/999")

    assert current_ipc["edition"] == "8U"
    assert legacy_ipc["edition"] == "4"
    assert current_ipc["texts"] != legacy_ipc["texts"]
    assert missing["match_status"] == "not_found"
    assert missing["labels"] == []
    assert missing["properties"] == []
    assert missing["documents"] == []

    with pytest.raises(EditionNotFoundError, match="9Z"):
        store.lookup("ipc", "G06F3/048", edition="9Z")
    with pytest.raises(PMGSQueryError, match="only for IPC"):
        store.lookup("fi", "G06F3/048", edition="8U")


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

    with pytest.raises(DocumentNotFoundError) as missing:
        store.get_document("doc-not-present")
    assert missing.value.as_dict()["code"] == "DOCUMENT_NOT_FOUND"
    with pytest.raises(PMGSQueryError, match="1 to 500"):
        store.search("")
    with pytest.raises(PMGSQueryError, match="between 1 and 100"):
        store.search("Synthetic", limit=101)
