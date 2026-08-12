from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmgs_reference.cli import main


def test_lookup_search_and_document_cli(
    synthetic_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = str(synthetic_database)
    assert main(["lookup", "fi", "G06F3/048", "--db", database, "--json"]) == 0
    lookup = json.loads(capsys.readouterr().out)
    assert lookup["normalized_code"] == "G06F3/048"

    assert (
        main(
            [
                "lookup",
                "ipc",
                "G06F3/048",
                "--ipc-version",
                "2006.01",
                "--db",
                database,
                "--json",
            ]
        )
        == 0
    )
    historical = json.loads(capsys.readouterr().out)
    assert historical["version"] == "2006.01"

    assert (
        main(
            [
                "search",
                "Synthetic interaction",
                "--scheme",
                "fi",
                "--db",
                database,
                "--json",
            ]
        )
        == 0
    )
    search = json.loads(capsys.readouterr().out)
    assert search["search_mode"] == "sqlite_fts5_trigram_lexical"
    assert search["results"][0]["code"] == "G06F3/048"

    assert (
        main(
            [
                "search",
                "Synthetic handbook",
                "--content-type",
                "document",
                "--db",
                database,
                "--json",
            ]
        )
        == 0
    )
    documents = json.loads(capsys.readouterr().out)
    document_id = documents["results"][0]["document_id"]
    assert main(["document", document_id, "--db", database, "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["document_id"] == document_id


def test_lookup_cli_returns_structured_not_found(
    synthetic_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(["lookup", "fi", "Z99Z99/999", "--db", str(synthetic_database), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["match_status"] == "not_found"
