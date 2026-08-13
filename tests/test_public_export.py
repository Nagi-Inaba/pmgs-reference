from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import jsonschema
import pytest
import yaml
from lxml import html

from pmgs_reference.cli import main
from pmgs_reference.publication import export_public, validate_public_export
from pmgs_reference.publication.model import fragment_id
from pmgs_reference.publication.policy import load_publication_policy
from pmgs_reference.publication.records import common_record
from pmgs_reference.publication.validation import _check_file, write_public_validation_report
from pmgs_reference.store import PMGSStore

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "tests" / "fixtures" / "publication-policy.yaml"
BASE_URL = "https://pmgs.example.test"
RELEASE = "JPPM2099001"


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _classification_storage_records(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    group_root = root / "releases" / RELEASE / "groups" / "classification"
    for path in group_root.rglob("[0-9][0-9][0-9].json"):
        chunk_records = _json(path)["records"]
        assert isinstance(chunk_records, list)
        records.extend(record for record in chunk_records if isinstance(record, dict))
    return records


@pytest.fixture(scope="module")
def public_pair(
    synthetic_database: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("public-export")
    first = root / "first"
    second = root / "second"
    first_result = export_public(
        synthetic_database,
        POLICY,
        first,
        base_url=BASE_URL,
        max_json_chunk_bytes=16384,
    )
    second_result = export_public(
        synthetic_database,
        POLICY,
        second,
        base_url=BASE_URL,
        max_json_chunk_bytes=16384,
    )
    assert first_result.tree_sha256 == second_result.tree_sha256
    return first, second


def test_public_export_is_byte_reproducible_and_self_validating(
    public_pair: tuple[Path, Path],
) -> None:
    first, second = public_pair
    assert _tree(first) == _tree(second)

    validation = validate_public_export(first)
    assert validation.valid is True
    assert validation.missing_objects == ()
    assert validation.unexpected_objects == ()
    assert validation.metadata_errors == ()
    assert validation.forbidden_files == ()
    assert validation.leakage_errors == ()
    assert validation.notice_errors == ()
    assert validation.coverage_errors == ()

    release_manifest_path = first / "releases" / RELEASE / "manifest.json"
    release_manifest = _json(release_manifest_path)
    schema = _json(ROOT / "schemas" / "release-manifest.schema.json")
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        release_manifest
    )
    assert release_manifest["base_url"] == BASE_URL
    assert release_manifest["generated_at"] == "2099-01-01T00:00:00Z"

    objects = release_manifest["objects"]
    assert isinstance(objects, list)
    for metadata in objects:
        assert isinstance(metadata, dict)
        target = first.joinpath(*str(metadata["key"]).split("/"))
        assert target.stat().st_size == metadata["bytes"]
        assert _sha256(target) == metadata["sha256"]


def test_public_validator_rejects_a_hard_link_before_reading(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    candidate = tmp_path / "hard-link-candidate"
    shutil.copytree(source, candidate)
    target = candidate / "api" / "v1" / "coverage.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    os.link(outside, target)

    with pytest.raises(ValueError, match="hard-linked file"):
        validate_public_export(candidate)


def test_public_validator_rejects_a_file_symlink_before_reading(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    candidate = tmp_path / "file-link-candidate"
    shutil.copytree(source, candidate)
    target = candidate / "api" / "v1" / "coverage.json"
    outside = tmp_path / "outside.json"
    outside.write_text('{"outside":"must not be read"}', encoding="utf-8")
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlink unavailable: {error}")

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        validate_public_export(candidate)


def test_public_validator_rejects_a_directory_symlink_or_reparse_point(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    candidate = tmp_path / "directory-link-candidate"
    shutil.copytree(source, candidate)
    target = candidate / "assets"
    shutil.rmtree(target)
    outside = tmp_path / "outside-assets"
    outside.mkdir()
    (outside / "webmcp.js").write_text("outside", encoding="utf-8")
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        validate_public_export(candidate)


def test_public_validator_rejects_a_symlink_root(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(source, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        validate_public_export(linked_root)


def test_public_validator_rejects_a_symlink_ancestor(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    shutil.copytree(source, real_parent / "candidate")
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        validate_public_export(linked_parent / "candidate")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction coverage")
def test_public_validator_rejects_a_windows_junction(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    candidate = tmp_path / "junction-candidate"
    shutil.copytree(source, candidate)
    target = candidate / "assets"
    shutil.rmtree(target)
    outside = tmp_path / "outside-junction-assets"
    outside.mkdir()
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction unavailable: {result.stderr.strip()}")

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        validate_public_export(candidate)


@pytest.mark.parametrize(
    "malicious_markup",
    [
        '<img src="//attacker.example/pixel">',
        '<iframe src="https://attacker.example/frame"></iframe>',
        '<form action="//attacker.example/collect"></form>',
        '<button formaction="https://attacker.example/collect">Send</button>',
        '<object data="/local-object"></object>',
        '<embed src="/local-plugin">',
        '<meta http-equiv="refresh" content="0;url=//attacker.example/">',
        '<div style="background:url(//attacker.example/pixel)">x</div>',
        "<style>body{background:url(https://attacker.example/pixel)}</style>",
        '<style>@import "https://attacker.example/style.css";</style>',
        '<link rel="stylesheet" href="//attacker.example/style.css">',
        '<link rel="canonical stylesheet" href="https://attacker.example/style.css">',
        '<base href="https://attacker.example/">',
        '<a href="//attacker.example/">Protocol-relative navigation</a>',
        '<img src="/local.png" srcset="https://attacker.example/large.png 2x">',
        '<iframe srcdoc="&lt;img src=//attacker.example/pixel&gt;"></iframe>',
        "<svg onload=\"fetch('//attacker.example/pixel')\"></svg>",
        '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><image '
        'xlink:href="https://attacker.example/pixel"/></svg>',
        '<a href="/local" ping="https://attacker.example/ping">Local</a>',
        '<video poster="https://attacker.example/poster.png"></video>',
        '<script type="application/ld+json" src="/assets/webmcp.js">{}</script>',
        '<meta http-equiv="content-security-policy" content="default-src *">',
    ],
)
def test_public_html_validation_rejects_active_external_vectors(
    tmp_path: Path, malicious_markup: str
) -> None:
    page = tmp_path / "malicious.html"
    page.write_text(
        f"<!doctype html><html><body>Readable{malicious_markup}</body></html>",
        encoding="utf-8",
    )

    assert _check_file(page, "malicious.html", None).html_errors


def test_public_html_validation_preserves_expected_links_and_webmcp(tmp_path: Path) -> None:
    page = tmp_path / "expected.html"
    page.write_text(
        """<!doctype html><html><head>
<link rel="canonical" href="https://pmgs.example.test/ja/">
<link rel="alternate" href="https://pmgs.example.test/en/">
<link rel="stylesheet" href="/assets/style.css">
<script src="/assets/webmcp.js" defer></script></head>
<body><a href="https://www.jpo.go.jp/source">JPO source</a></body></html>""",
        encoding="utf-8",
    )

    assert _check_file(page, "expected.html", None).html_errors == ()


def test_public_css_validation_rejects_external_resources(tmp_path: Path) -> None:
    external = tmp_path / "external.css"
    external.write_text(
        '@import "https://attacker.example/base.css";\n'
        "body{background:url(//attacker.example/pixel)}\n",
        encoding="utf-8",
    )
    local = tmp_path / "local.css"
    local.write_text("body{background:url(/assets/background.svg)}\n", encoding="utf-8")

    assert _check_file(external, "external.css", None).html_errors
    assert _check_file(local, "local.css", None).html_errors == ()


def test_batched_group_loading_preserves_every_output_byte(
    synthetic_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_module = importlib.import_module("pmgs_reference.publication.export")
    one_group_at_a_time = tmp_path / "one-group-at-a-time"
    batched = tmp_path / "batched"

    monkeypatch.setattr(export_module, "_GROUP_BATCH_CONCEPTS", 1)
    monkeypatch.setattr(export_module, "_WRITE_WORKERS", 1)
    export_module.export_public(
        synthetic_database,
        POLICY,
        one_group_at_a_time,
        base_url=BASE_URL,
        max_json_chunk_bytes=16384,
    )
    monkeypatch.setattr(export_module, "_GROUP_BATCH_CONCEPTS", 1_000)
    monkeypatch.setattr(export_module, "_WRITE_WORKERS", 4)
    batched_result = export_module.export_public(
        synthetic_database,
        POLICY,
        batched,
        base_url=BASE_URL,
        max_json_chunk_bytes=16384,
    )

    assert _tree(one_group_at_a_time) == _tree(batched)
    assert validate_public_export(batched).tree_sha256 == batched_result.tree_sha256


def test_parallel_validation_is_result_deterministic(
    public_pair: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_module = importlib.import_module("pmgs_reference.publication.validation")
    root, _ = public_pair
    monkeypatch.setattr(validation_module, "_VALIDATION_WORKERS", 1)
    sequential = validation_module.validate_public_export(root)
    monkeypatch.setattr(validation_module, "_VALIDATION_WORKERS", 4)
    parallel = validation_module.validate_public_export(root)

    assert sequential.as_dict() == parallel.as_dict()


def test_json_leakage_check_distinguishes_newline_escapes_from_paths(tmp_path: Path) -> None:
    notation = tmp_path / "notation.json"
    notation.write_text(json.dumps({"text": "Additional code B:\nnext item"}), encoding="utf-8")
    assert _check_file(notation, "notation.json", None).leakage_errors == ()

    windows_path = tmp_path / "windows-path.json"
    windows_path.write_text(
        json.dumps({"debug_path": r"C:\Users\Example\pmgs.sqlite"}), encoding="utf-8"
    )
    assert _check_file(windows_path, "windows-path.json", None).leakage_errors == (
        "windows-path.json: local absolute path detected",
    )

    unix_path = tmp_path / "unix-path.json"
    unix_path.write_text(json.dumps({"debug_path": "/home/example/pmgs.sqlite"}), encoding="utf-8")
    assert _check_file(unix_path, "unix-path.json", None).leakage_errors == (
        "unix-path.json: local absolute path detected",
    )


def test_every_classification_has_a_readable_page_and_schema_valid_api_projection(
    public_pair: tuple[Path, Path],
) -> None:
    root, _ = public_pair
    record_schema = _json(ROOT / "schemas" / "classification-record.schema.json")
    validator = jsonschema.Draft202012Validator(
        record_schema, format_checker=jsonschema.FormatChecker()
    )
    chunk_paths = sorted((root / "releases" / RELEASE / "groups").rglob("[0-9][0-9][0-9].json"))
    assert chunk_paths

    for chunk_path in chunk_paths:
        chunk = _json(chunk_path)
        records = chunk["records"]
        assert isinstance(records, list) and records
        chunk_id = str(chunk["chunk_id"])
        group_manifest = _json(chunk_path.parent / "manifest.json")
        chunks = group_manifest["chunks"]
        assert isinstance(chunks, list)
        chunk_metadata = next(item for item in chunks if item["chunk_id"] == chunk_id)
        site = chunk_metadata["site"]
        assert isinstance(site, dict)

        seen_fragments: set[str] = set()
        for storage_record in records:
            assert isinstance(storage_record, dict)
            fragment = str(storage_record["fragment"])
            assert fragment not in seen_fragments
            seen_fragments.add(fragment)
            canonical_urls = storage_record["canonical_urls"]
            assert isinstance(canonical_urls, dict)
            for language, canonical_url in canonical_urls.items():
                assert isinstance(language, str) and isinstance(canonical_url, str)
                expected_suffix = f"#{fragment}"
                assert canonical_url.endswith(expected_suffix)
                if chunk_id != "001":
                    assert f"/{chunk_id}{expected_suffix}" in canonical_url
                site_metadata = site[language]
                assert isinstance(site_metadata, dict)
                html_path = root.joinpath(*str(site_metadata["html_key"]).split("/"))
                document = html.fromstring(html_path.read_bytes())
                assert document.get_element_by_id(fragment) is not None
                assert document.xpath('//script[@src="/assets/webmcp.js"]')
                projected = common_record(storage_record, language)
                validator.validate(projected)
                projected_sources = projected["sources"]
                assert isinstance(projected_sources, list) and projected_sources
                for source in projected_sources:
                    assert source["owner"] == "JPO"
                    assert source["original_url"] == (
                        "https://www.jpo.go.jp/system/laws/sesaku/data/download.html"
                    )
                    assert source["attribution"] == "Copyright (C) TEST 2026"

    fi_chunk = _json(
        root / "releases" / RELEASE / "groups" / "classification" / "G06F3" / "001.json"
    )
    fi_record = next(
        item
        for item in fi_chunk["records"]  # type: ignore[index]
        if item["scheme"] == "fi" and item["normalized_code"] == "G06F3/048"
    )
    assert isinstance(fi_record, dict)
    assert any(item["kind"] == "fi_handbook" for item in fi_record["texts"])
    assert any(item["kind"] == "fi_amendment" for item in fi_record["texts"])
    assert any(item["kind"] == "fi_handbook" for item in fi_record["documents"])


def test_ipc_storage_bundle_keeps_current_and_historical_revisions_together(
    public_pair: tuple[Path, Path],
) -> None:
    root, _ = public_pair
    storage_records = [
        record
        for path in (root / "releases" / RELEASE / "groups" / "classification").rglob(
            "[0-9][0-9][0-9].json"
        )
        for record in _json(path)["records"]  # type: ignore[index]
    ]
    ipc = next(
        record
        for record in storage_records
        if record["scheme"] == "ipc"
        and record["edition"] == "8U"
        and record["normalized_code"] == "G06F3/048"
    )

    assert ipc["schema_version"] == "2.0"
    assert ipc["reference_date"] == "2026-01-01"
    assert ipc["version"] == "2021.01"
    assert ipc["match_status"] == "exact"
    revisions = ipc["revision_records"]
    assert {item["version"] for item in revisions} == {"2006.01", "2021.01"}
    assert all(item["sources"] for item in revisions)
    assert all(
        label["source_id"] and label["locator"] for item in revisions for label in item["labels"]
    )
    expired = next(
        record
        for record in storage_records
        if record["scheme"] == "ipc" and record["normalized_code"] == "G06F3/050"
    )
    assert expired["match_status"] == "not_valid_at_release"
    assert expired["texts"] == []
    assert expired["available_versions"]
    assert expired["sources"]
    assert not any(record["record_status"] == "reference_only" for record in storage_records)
    coverage = _json(root / "api" / "v1" / "coverage.json")
    assert coverage["classification.reference_only_excluded"] >= 1


def test_public_export_rejects_a_revision_bundle_over_the_configured_limit(
    synthetic_database: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="revision bundle exceeds the 256 KiB safety limit"):
        export_public(
            synthetic_database,
            POLICY,
            tmp_path / "too-small",
            base_url=BASE_URL,
            max_json_chunk_bytes=256,
        )


def test_public_export_keeps_active_revision_relations_for_worker_paging(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "relation-paging.sqlite"
    shutil.copy2(synthetic_database, database)
    with sqlite3.connect(database) as connection:
        source_concept, source_file = connection.execute(
            "SELECT concept_id, source_file_id FROM concept "
            "WHERE scheme = 'fi' AND normalized_code = 'G06F3/048'"
        ).fetchone()
        for index in range(55):
            target = connection.execute(
                "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                "concept_type, record_status, source_file_id, source_locator) "
                "VALUES ('JPPM2099001', 'fi', '', ?, ?, 'term', 'canonical', ?, 'test')",
                (f"Z99Z{index:04d}/99", f"Z99Z{index:04d}/99", source_file),
            ).lastrowid
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, source_file_id, "
                "source_locator) VALUES (?, '', ?, 'test')",
                (target, source_file),
            )
            connection.execute(
                "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
                "source_locator) VALUES (?, ?, 'see_also', ?, ?)",
                (source_concept, target, source_file, f"paging:{index}"),
            )

    root = tmp_path / "relation-paging"
    export_public(
        database,
        POLICY,
        root,
        base_url=BASE_URL,
        max_json_chunk_bytes=1_048_576,
    )
    records = _classification_storage_records(root)
    record = next(
        item
        for item in records
        if item["scheme"] == "fi" and item["normalized_code"] == "G06F3/048"
    )

    assert record["relation_count"] >= 55
    assert len(record["relations"]) == 50
    assert len(record["revision_records"][0]["relations"]) == record["relation_count"]


def test_public_export_preserves_revision_text_sequence(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "text-sequence.sqlite"
    shutil.copy2(synthetic_database, database)
    with sqlite3.connect(database) as connection:
        revision_id, source_file = connection.execute(
            "SELECT cr.revision_id, cr.source_file_id FROM concept_revision cr "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'fi' "
            "AND c.normalized_code = 'G06F3/048'"
        ).fetchone()
        connection.execute(
            "INSERT INTO concept_text(revision_id, language, kind, sequence_number, text, "
            "translation_status, source_file_id, source_locator) "
            "VALUES (?, 'ja', 'sequence_test', 2, 'Second', 'official', ?, 'a-locator')",
            (revision_id, source_file),
        )
        connection.execute(
            "INSERT INTO concept_text(revision_id, language, kind, sequence_number, text, "
            "translation_status, source_file_id, source_locator) "
            "VALUES (?, 'ja', 'sequence_test', 1, 'First', 'official', ?, 'z-locator')",
            (revision_id, source_file),
        )

    root = tmp_path / "text-sequence"
    export_public(database, POLICY, root, base_url=BASE_URL, max_json_chunk_bytes=16384)
    record = next(
        item
        for item in _classification_storage_records(root)
        if item["scheme"] == "fi" and item["normalized_code"] == "G06F3/048"
    )
    sequence_texts = [item["text"] for item in record["texts"] if item["kind"] == "sequence_test"]
    assert sequence_texts == ["First", "Second"]


def test_public_export_deduplicates_relations_like_local_lookup(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "duplicate-public-relations.sqlite"
    shutil.copy2(synthetic_database, database)
    with sqlite3.connect(database) as connection:
        low_source_id = int(
            connection.execute("SELECT MIN(file_id) FROM source_file").fetchone()[0]
        )
        high_source_id = int(
            connection.execute("SELECT MAX(file_id) FROM source_file").fetchone()[0]
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
        target_id = int(
            connection.execute(
                "INSERT INTO concept(release_id, scheme, edition, code, normalized_code, "
                "concept_type, record_status, source_file_id, source_locator) "
                "VALUES ('JPPM2099001', 'fi', '', 'Z99Z9998/99', 'Z99Z9998/99', "
                "'synthetic_reference', 'reference_only', ?, 'duplicate-public-target')",
                (low_source_id,),
            ).lastrowid
        )
        unversioned_target_revision = int(
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, valid_to, "
                "level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '', NULL, NULL, NULL, 1, ?, 'duplicate-public-target')",
                (target_id, low_source_id),
            ).lastrowid
        )
        versioned_target_revision = int(
            connection.execute(
                "INSERT INTO concept_revision(concept_id, version_indicator, valid_from, valid_to, "
                "level, sequence_number, source_file_id, source_locator) "
                "VALUES (?, '2026.02', NULL, NULL, NULL, 2, ?, 'versioned-public-target')",
                (target_id, high_source_id),
            ).lastrowid
        )
        connection.execute(
            "INSERT INTO relation(from_concept_id, to_concept_id, kind, source_file_id, "
            "source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'z-concept')",
            (origin_id, target_id, high_source_id),
        )
        connection.execute(
            "INSERT INTO revision_relation(from_revision_id, to_revision_id, kind, "
            "source_file_id, source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'a-revision')",
            (origin_revision_id, unversioned_target_revision, low_source_id),
        )
        connection.execute(
            "INSERT INTO revision_relation(from_revision_id, to_revision_id, kind, "
            "source_file_id, source_locator) VALUES (?, ?, 'duplicate_lineage', ?, 'versioned')",
            (origin_revision_id, versioned_target_revision, high_source_id),
        )

    local_record = PMGSStore.open(database).lookup("fi", "G06F3/048", relation_limit=200)
    assert local_record is not None
    root = tmp_path / "duplicate-public-relations"
    export_public(
        database,
        POLICY,
        root,
        base_url=BASE_URL,
        max_json_chunk_bytes=1_048_576,
    )
    public_record = next(
        item
        for item in _classification_storage_records(root)
        if item["scheme"] == "fi" and item["normalized_code"] == "G06F3/048"
    )

    assert public_record["relation_count"] == local_record["relation_count"]
    assert public_record["next_relation_offset"] == local_record["next_relation_offset"]
    assert public_record["relations"] == local_record["relations"]
    active_revision = next(
        item
        for item in public_record["revision_records"]
        if item["version"] == public_record["version"]
    )
    assert active_revision["relations"] == local_record["relations"]
    duplicates = [
        item for item in public_record["relations"] if item["type"] == "duplicate_lineage"
    ]
    assert [(item["version"], item["locator"]) for item in duplicates] == [
        (None, "a-revision"),
        ("2026.02", "versioned"),
    ]


def test_public_export_rejects_a_classification_bundle_over_256_kib_even_with_larger_chunks(
    synthetic_database: Path, tmp_path: Path
) -> None:
    database = tmp_path / "oversized-classification.sqlite"
    shutil.copy2(synthetic_database, database)
    with sqlite3.connect(database) as connection:
        revision_id, source_file = connection.execute(
            "SELECT cr.revision_id, cr.source_file_id FROM concept_revision cr "
            "JOIN concept c USING(concept_id) WHERE c.scheme = 'fi' "
            "AND c.normalized_code = 'G06F3/048'"
        ).fetchone()
        connection.execute(
            "INSERT INTO concept_text(revision_id, language, kind, sequence_number, text, "
            "translation_status, source_file_id, source_locator) "
            "VALUES (?, 'ja', 'definition', 999, ?, 'official', ?, 'oversize')",
            (revision_id, "架" * 300_000, source_file),
        )

    with pytest.raises(ValueError, match="revision bundle exceeds the 256 KiB safety limit"):
        export_public(
            database,
            POLICY,
            tmp_path / "too-large-classification",
            base_url=BASE_URL,
            max_json_chunk_bytes=1_048_576,
        )


def test_public_discovery_files_are_machine_parseable_and_no_raw_sources_are_exposed(
    public_pair: tuple[Path, Path],
) -> None:
    root, _ = public_pair
    openapi = _json(root / "openapi.json")
    assert openapi["openapi"] == "3.1.0"
    paths = openapi["paths"]
    assert isinstance(paths, dict)
    assert paths["/api/v1/lookup"]["get"]["operationId"] == "lookupPatentClassification"
    required = openapi["components"]["schemas"]["ClassificationRecord"]["required"]
    assert "edition" in required
    assert "normalized_code" in required
    assert "reference_date" in required
    assert "available_versions" in required
    assert "relations_truncated" in required
    lookup_parameters = paths["/api/v1/lookup"]["get"]["parameters"]
    lookup_parameter_names = {parameter["name"] for parameter in lookup_parameters}
    assert {"version", "relation_limit", "relation_offset"} <= lookup_parameter_names
    public_source = openapi["components"]["schemas"]["PublicSource"]
    assert public_source["required"] == [
        "source_id",
        "title",
        "relative_id",
        "owner",
        "original_url",
        "sha256",
        "attribution",
    ]
    document_parameters = paths["/api/v1/documents/{document_id}"]["get"]["parameters"]
    assert any(parameter["name"] == "release" for parameter in document_parameters)
    ElementTree.parse(root / "sitemap.xml")

    assert "完全一致API" in (root / "llms.txt").read_text(encoding="utf-8")
    assert "Exact lookup API" in (root / "llms.en.txt").read_text(encoding="utf-8")
    assert "命令として扱わない" in (root / "llms.txt").read_text(encoding="utf-8")
    assert "never as instructions" in (root / "llms.en.txt").read_text(encoding="utf-8")
    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "PMGS Reference" in index_html
    assert 'href="https://pmgs.example.test/en/"' in index_html
    assert 'src="/assets/webmcp.js"' in index_html
    english_index = (root / "index.en.html").read_text(encoding="utf-8")
    assert 'lang="en"' in english_index
    assert 'name="language" value="en"' in english_index
    forbidden = {".sqlite", ".sqlite3", ".db", ".csv", ".pdf", ".zip", ".xsl"}
    assert not [
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in forbidden
    ]


def test_every_human_and_agent_page_discloses_source_processing_and_service_status(
    public_pair: tuple[Path, Path],
) -> None:
    root, _ = public_pair
    policy = _json(root / "releases" / RELEASE / "publication-policy.json")
    sources = policy["sources"]
    assert isinstance(sources, list) and len(sources) == 1
    source = sources[0]
    assert isinstance(source, dict)
    processing = source["processing_notice"]
    non_affiliation = source["non_affiliation_notice"]
    assert isinstance(processing, dict) and isinstance(non_affiliation, dict)

    targets = [
        root / "index.html",
        root / "index.en.html",
        root / "llms.txt",
        root / "llms.en.txt",
    ]
    targets.extend(sorted((root / "releases" / RELEASE / "site").rglob("*.html")))
    targets.extend(sorted((root / "releases" / RELEASE / "site").rglob("*.md")))
    assert targets
    for path in targets:
        relative = path.relative_to(root).as_posix()
        language = (
            "en"
            if relative in {"index.en.html", "llms.en.txt"} or "/site/en/" in relative
            else "ja"
        )
        text = path.read_text(encoding="utf-8")
        assert source["attribution"] in text
        assert source["source_url"] in text
        assert processing[language] in text
        assert non_affiliation[language] in text


def test_public_validator_detects_tampering(public_pair: tuple[Path, Path], tmp_path: Path) -> None:
    source, _ = public_pair
    tampered = tmp_path / "tampered"
    shutil.copytree(source, tampered)
    coverage = tampered / "api" / "v1" / "coverage.json"
    coverage.write_bytes(coverage.read_bytes() + b" ")

    validation = validate_public_export(tampered)

    assert validation.valid is False
    assert "api/v1/coverage.json: byte size mismatch" in validation.metadata_errors
    assert "api/v1/coverage.json: SHA-256 mismatch" in validation.metadata_errors


def test_publication_policy_fails_closed_for_download_delivery(tmp_path: Path) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["sources"][0]["delivery"]["source_archive_download"] = True
    unsafe_policy = tmp_path / "unsafe-policy.yaml"
    unsafe_policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="must remain disabled"):
        load_publication_policy(unsafe_policy)


def test_publication_policy_v1_fails_closed_for_ambiguous_multiple_sources(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["sources"].append(dict(payload["sources"][0]))
    ambiguous_policy = tmp_path / "ambiguous-policy.yaml"
    ambiguous_policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one source"):
        load_publication_policy(ambiguous_policy)


def test_public_export_rejects_attribution_that_does_not_match_source(
    synthetic_database: Path,
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["sources"][0]["attribution"] = "Incorrect attribution"
    mismatched_policy = tmp_path / "mismatched-policy.yaml"
    mismatched_policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    output = tmp_path / "public"

    with pytest.raises(ValueError, match="does not match release_source"):
        export_public(synthetic_database, mismatched_policy, output, base_url=BASE_URL)

    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "Wrong owner"),
        ("source_url", "https://example.test/wrong-source"),
    ],
)
def test_public_export_rejects_policy_identity_mismatches(
    synthetic_database: Path,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["sources"][0][field] = value
    mismatched_policy = tmp_path / f"mismatched-{field}.yaml"
    mismatched_policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match release_source"):
        export_public(
            synthetic_database,
            mismatched_policy,
            tmp_path / f"public-{field}",
            base_url=BASE_URL,
        )


def test_public_validator_detects_a_missing_required_notice(
    public_pair: tuple[Path, Path], tmp_path: Path
) -> None:
    source, _ = public_pair
    tampered = tmp_path / "missing-notice"
    shutil.copytree(source, tampered)
    page = next((tampered / "releases" / RELEASE / "site" / "ja").rglob("*.md"))
    content = page.read_text(encoding="utf-8")
    page.write_text(
        content.replace("このページは、合成テストデータを変換して作成しています。", ""),
        encoding="utf-8",
    )

    validation = validate_public_export(tampered)

    assert validation.valid is False
    assert f"{page.relative_to(tampered).as_posix()}: required public notice is missing" in (
        validation.notice_errors
    )


def test_public_identifiers_escape_punctuation_without_collisions() -> None:
    values = {
        fragment_id("fi", None, "G06F3/048"),
        fragment_id("fi", None, "G06F3:048"),
        fragment_id("ipc", "8U", "G06F3/048"),
        fragment_id("ipc", "8/U", "G06F3/048"),
    }
    assert len(values) == 4
    assert all("/" not in value and ":" not in value for value in values)


def test_export_and_validate_public_cli(
    synthetic_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "public"
    report = tmp_path / "export-report.json"
    assert (
        main(
            [
                "export-public",
                "--db",
                str(synthetic_database),
                "--policy",
                str(POLICY),
                "--output",
                str(output),
                "--base-url",
                BASE_URL,
                "--report",
                str(report),
            ]
        )
        == 0
    )
    export_result = json.loads(capsys.readouterr().out)
    assert export_result["release_id"] == RELEASE
    assert export_result["max_json_chunk_bytes"] == 262_144
    assert report.exists()

    validation_report = tmp_path / "validation-report.json"
    assert (
        main(
            [
                "validate-public",
                str(output),
                "--report",
                str(validation_report),
            ]
        )
        == 0
    )
    validation_result = json.loads(capsys.readouterr().out)
    assert validation_result["valid"] is True
    assert json.loads(validation_report.read_text(encoding="utf-8"))["valid"] is True


def test_audit_public_cli_requires_two_equal_validated_exports(
    synthetic_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_export_report = tmp_path / "first-export.json"
    second_export_report = tmp_path / "second-export.json"
    first_validation_report = tmp_path / "first-validation.json"
    second_validation_report = tmp_path / "second-validation.json"
    audit_report = tmp_path / "audit.json"

    export_public(
        synthetic_database,
        POLICY,
        first,
        base_url=BASE_URL,
        report_path=first_export_report,
    )
    export_public(
        synthetic_database,
        POLICY,
        second,
        base_url=BASE_URL,
        report_path=second_export_report,
    )
    write_public_validation_report(validate_public_export(first), first_validation_report)
    write_public_validation_report(validate_public_export(second), second_validation_report)
    connection = sqlite3.connect(synthetic_database)
    try:
        source_manifest_sha256 = str(
            connection.execute("SELECT source_manifest_sha256 FROM release").fetchone()[0]
        )
    finally:
        connection.close()

    arguments = [
        "audit-public",
        "--db",
        str(synthetic_database),
        "--first-root",
        str(first),
        "--second-root",
        str(second),
        "--first-export-report",
        str(first_export_report),
        "--second-export-report",
        str(second_export_report),
        "--first-validation-report",
        str(first_validation_report),
        "--second-validation-report",
        str(second_validation_report),
        "--expected-database-sha256",
        _sha256(synthetic_database),
        "--expected-source-manifest-sha256",
        source_manifest_sha256,
        "--report",
        str(audit_report),
    ]
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is True
    assert result["failures"] == []
    assert all(result["checks"].values())
    assert result["largest_chunk_bytes"] <= result["max_json_chunk_bytes"]
    assert _json(audit_report) == result

    invalid_validation = _json(second_validation_report)
    invalid_validation["valid"] = False
    second_validation_report.write_text(json.dumps(invalid_validation), encoding="utf-8")
    assert main(arguments[:-2]) == 1
    failed_result = json.loads(capsys.readouterr().out)
    assert failed_result["ready"] is False
    assert "validations.equal" in failed_result["failures"]
    assert "validations.second_ready" in failed_result["failures"]


def test_export_refuses_to_overwrite_existing_output(
    synthetic_database: Path, tmp_path: Path
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        export_public(synthetic_database, POLICY, output, base_url=BASE_URL)
