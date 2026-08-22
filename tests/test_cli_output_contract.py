from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmgs_reference.cli import main


def test_json_mode_returns_one_structured_error_for_runtime_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.sqlite"

    exit_code = main(["doctor", "--db", str(missing), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert captured.err == ""
    assert payload == {
        "schema_version": "1.0",
        "status": "failed",
        "command": "doctor",
        "error": {
            "code": "FILE_NOT_FOUND",
            "message": "PMGS Reference database was not found",
        },
    }


def test_english_ui_language_applies_to_help_and_parse_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["--ui-language", "en", "--help"])
    help_output = capsys.readouterr()

    assert help_exit.value.code == 0
    assert "usage:" in help_output.out
    assert "options:" in help_output.out
    assert "使い方:" not in help_output.out

    with pytest.raises(SystemExit) as error_exit:
        main(["--ui-language", "en", "lookup", "cpc", "G06F3/048"])
    error_output = capsys.readouterr()

    assert error_exit.value.code == 2
    assert "error:" in error_output.err
    assert "エラー:" not in error_output.err


def test_json_error_codes_do_not_change_with_ui_language(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.sqlite"

    japanese = main(
        ["--ui-language", "ja", "doctor", "--db", str(missing), "--json"]
    )
    japanese_payload = json.loads(capsys.readouterr().out)
    english = main(
        ["--ui-language", "en", "doctor", "--db", str(missing), "--json"]
    )
    english_payload = json.loads(capsys.readouterr().out)

    assert japanese == english == 1
    assert japanese_payload["error"]["code"] == english_payload["error"]["code"]
