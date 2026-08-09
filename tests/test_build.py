from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pmgs_reference.cli import main
from pmgs_reference.ingest.build import build_database
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
