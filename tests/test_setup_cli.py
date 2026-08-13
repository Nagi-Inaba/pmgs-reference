from __future__ import annotations

import json
from pathlib import Path

import pytest

import pmgs_reference.cli as cli_module
import pmgs_reference.setup as local_setup_module
from pmgs_reference import __version__
from pmgs_reference.cli import main
from pmgs_reference.client_integration import ClientTarget


def test_setup_help_and_package_version_are_public(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["setup", "--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    assert "使い方:" in help_text
    assert "位置引数:" in help_text
    assert "オプション:" in help_text
    assert "このヘルプを表示して終了" in help_text
    assert "展開済みPMGSディレクトリ" in help_text
    for option in [
        "source",
        "--release",
        "--data-dir",
        "--client",
        "--register",
        "--no-register",
        "--non-interactive",
        "--dry-run",
        "--json",
        "--language",
    ]:
        assert option in help_text

    with pytest.raises(SystemExit) as version_exit:
        main(["--version"])
    assert version_exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"pmgs {__version__}"


def test_json_setup_requires_an_explicit_registration_choice(
    synthetic_pmgs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "setup",
            str(synthetic_pmgs),
            "--release",
            "JPPM2099001",
            "--data-dir",
            str(tmp_path / "data"),
            "--client",
            "none",
            "--dry-run",
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert result == 2
    payload = json.loads(captured.out)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "SETUP_USAGE"
    assert captured.err == ""
    assert not (tmp_path / "data").exists()


def test_json_dry_run_writes_one_result_to_stdout_and_progress_to_stderr(
    synthetic_pmgs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_root = tmp_path / "data"

    result = main(
        [
            "setup",
            str(synthetic_pmgs),
            "--release",
            "JPPM2099001",
            "--data-dir",
            str(data_root),
            "--client",
            "none",
            "--no-register",
            "--non-interactive",
            "--dry-run",
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload["status"] == "dry_run"
    assert payload["inventory"]["file_count"] == 26
    assert "棚卸し" in captured.err
    assert not data_root.exists()


def test_human_setup_reports_the_client_that_failed(
    synthetic_pmgs: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ClientTarget("codex", tmp_path / "codex.exe")
    monkeypatch.setattr(cli_module, "detect_client_targets", lambda _selection: (target,))
    monkeypatch.setattr(
        local_setup_module,
        "integrate_clients",
        lambda *args, **kwargs: [
            {
                "client": "codex",
                "status": "conflict",
                "mcp": "conflict",
                "skill": "not_checked",
                "restart_required": False,
                "error": "a different pmgs-reference MCP server already exists",
            }
        ],
    )

    result = main(
        [
            "setup",
            str(synthetic_pmgs),
            "--release",
            "JPPM2099001",
            "--data-dir",
            str(tmp_path / "data"),
            "--client",
            "codex",
            "--register",
        ]
    )
    captured = capsys.readouterr()

    assert result == 1
    assert "PMGS setup: partial_failed" in captured.out
    assert "クライアント codex: conflict" in captured.err
    assert "different pmgs-reference MCP server" in captured.err
