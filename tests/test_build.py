from __future__ import annotations

import errno
import json
import sqlite3
from pathlib import Path

import pytest

import pmgs_reference.ingest.build as build_module
from pmgs_reference.cli import main
from pmgs_reference.ingest.build import build_database
from pmgs_reference.ingest.inventory import build_inventory
from pmgs_reference.validation import validate_database


def _scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def test_build_creates_complete_queryable_synthetic_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    report_path = tmp_path / "build-report.json"

    result = build_database(
        synthetic_pmgs,
        release_id="JPPM2099001",
        output_path=database_path,
        report_path=report_path,
    )

    assert database_path.exists()
    assert not database_path.with_name(f".{database_path.name}.tmp").exists()
    assert result.release_id == "JPPM2099001"
    assert result.source_file_count == 26
    assert result.error_count == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["database_sha256"] == result.database_sha256

    with sqlite3.connect(database_path) as connection:
        assert _scalar(connection, "SELECT COUNT(*) FROM source_file") == 26
        assert _scalar(connection, "SELECT COUNT(*) FROM source_record") >= 25
        assert _scalar(connection, "SELECT COUNT(*) FROM concept") >= 10
        assert _scalar(connection, "SELECT COUNT(*) FROM document") >= 8
        assert _scalar(connection, "SELECT COUNT(*) FROM document_text") >= 8
        assert _scalar(connection, "SELECT COUNT(*) FROM relation") >= 5
        rows = connection.execute(
            "SELECT scheme, edition, normalized_code FROM concept "
            "WHERE normalized_code = 'G06F3/048' ORDER BY scheme, edition"
        ).fetchall()
        assert ("fi", "", "G06F3/048") in rows
        assert ("ipc", "8U", "G06F3/048") in rows
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE concept_type = 'concordance_reference'",
            )
            == 2
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'theme'",
            )
            == 1
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept WHERE scheme = 'fterm' AND concept_type = 'term'",
            )
            == 2
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM concept_text_fts WHERE concept_text_fts MATCH 'Synthetic'",
            )
            > 0
        )
        assert (
            _scalar(
                connection,
                "SELECT COUNT(*) FROM document_text_fts WHERE document_text_fts MATCH 'Synthetic'",
            )
            > 0
        )
        locator_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT text FROM document_text "
                "WHERE document_id = ? AND source_locator = ?",
                ("missing", "page:1"),
            )
        )
        assert "document_text_locator_idx" in locator_plan


def test_validate_database_checks_integrity_and_expected_counts(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)

    validation = validate_database(database_path)

    assert validation.valid is True
    assert validation.integrity_check == "ok"
    assert validation.foreign_key_error_count == 0
    assert validation.build_error_count == 0
    assert validation.counts["source_file"] == 26
    assert validation.regression_checks == {}
    assert validation.database_file == "pmgs-reference.sqlite"
    assert len(validation.database_sha256) == 64


def test_build_and_validate_cli_emit_machine_readable_results(
    synthetic_pmgs: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    assert (
        main(
            [
                "build",
                str(synthetic_pmgs),
                "--release",
                "JPPM2099001",
                "--output",
                str(database_path),
            ]
        )
        == 0
    )
    build_output = json.loads(capsys.readouterr().out)
    assert build_output["source_file_count"] == 26

    assert main(["validate", str(database_path)]) == 0
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output["valid"] is True


def test_validate_cli_writes_report(
    synthetic_pmgs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    report_path = tmp_path / "validation-report.json"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert main(["validate", str(database_path), "--report", str(report_path)]) == 0

    capsys.readouterr()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["database_file"] == database_path.name
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")


def test_build_refuses_to_overwrite_an_existing_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", database_path)
    before = database_path.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert database_path.read_bytes() == before


def test_build_accepts_a_precomputed_inventory(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = build_inventory(synthetic_pmgs)

    def unexpected_inventory(_source: Path) -> object:
        raise AssertionError("build_database must reuse the supplied inventory")

    monkeypatch.setattr("pmgs_reference.ingest.build.build_inventory", unexpected_inventory)
    result = build_database(
        synthetic_pmgs,
        "JPPM2099001",
        tmp_path / "pmgs-reference.sqlite",
        inventory=inventory,
    )

    assert result.source_manifest_sha256 == inventory.logical_sha256


def test_build_falls_back_when_hard_links_are_unavailable(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    monkeypatch.setattr(build_module.os, "link", unsupported_link)

    result = build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert validate_database(database_path).valid is True
    assert result.database_sha256 == validate_database(database_path).database_sha256
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_cleans_temporary_files_when_fallback_promotion_fails(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    def failed_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(build_module.os, "link", unsupported_link)
    monkeypatch.setattr(build_module.os, "replace", failed_replace)

    with pytest.raises(OSError, match="simulated promotion failure"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert not database_path.exists()
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))


def test_build_fallback_does_not_overwrite_a_racing_destination(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "pmgs-reference.sqlite"
    existing_bytes = b"concurrent writer"

    def racing_link(_source: Path, destination: Path) -> None:
        destination.write_bytes(existing_bytes)
        raise OSError(errno.EXDEV, "simulated hard-link limitation")

    monkeypatch.setattr(build_module.os, "link", racing_link)

    with pytest.raises(FileExistsError, match="already exists"):
        build_database(synthetic_pmgs, "JPPM2099001", database_path)

    assert database_path.read_bytes() == existing_bytes
    assert not list(tmp_path.glob(f".{database_path.name}-*.tmp"))
