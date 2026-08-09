from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sqlite3
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
        max_json_chunk_bytes=4096,
    )
    second_result = export_public(
        synthetic_database,
        POLICY,
        second,
        base_url=BASE_URL,
        max_json_chunk_bytes=4096,
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
        max_json_chunk_bytes=4096,
    )
    monkeypatch.setattr(export_module, "_GROUP_BATCH_CONCEPTS", 1_000)
    monkeypatch.setattr(export_module, "_WRITE_WORKERS", 4)
    batched_result = export_module.export_public(
        synthetic_database,
        POLICY,
        batched,
        base_url=BASE_URL,
        max_json_chunk_bytes=4096,
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
                    assert source["owner"] == "Test Fixture"
                    assert source["original_url"] == "https://example.test/synthetic-pmgs"
                    assert source["attribution"] == "Copyright (C) TEST 2026"

    fi_chunk = _json(
        root / "releases" / RELEASE / "groups" / "classification" / "G06F3" / "001.json"
    )
    fi_record = fi_chunk["records"][0]  # type: ignore[index]
    assert isinstance(fi_record, dict)
    assert any(item["kind"] == "fi_handbook" for item in fi_record["texts"])
    assert any(item["kind"] == "fi_amendment" for item in fi_record["texts"])
    assert any(item["kind"] == "fi_handbook" for item in fi_record["documents"])


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

    assert "Exact lookup API" in (root / "llms.txt").read_text(encoding="utf-8")
    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "PMGS Reference" in index_html
    assert 'src="/assets/webmcp.js"' in index_html
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

    targets = [root / "index.html", root / "llms.txt"]
    targets.extend(sorted((root / "releases" / RELEASE / "site").rglob("*.html")))
    targets.extend(sorted((root / "releases" / RELEASE / "site").rglob("*.md")))
    assert targets
    for path in targets:
        relative = path.relative_to(root).as_posix()
        language = "en" if relative == "llms.txt" or "/site/en/" in relative else "ja"
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

    with pytest.raises(ValueError, match="does not match the database COPYRGHT"):
        export_public(synthetic_database, mismatched_policy, output, base_url=BASE_URL)

    assert not output.exists()


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
