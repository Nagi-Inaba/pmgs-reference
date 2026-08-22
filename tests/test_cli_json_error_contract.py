from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import pmgs_reference.cli as cli_module
from pmgs_reference.cli import main
from pmgs_reference.data_paths import CurrentPointerError
from pmgs_reference.ingest.build import BuildError

_SECRET = "pmgs-secret-token-123"


def _assert_json_error(
    captured: pytest.CaptureResult[str],
    *,
    command: str,
    code: str,
    message: str,
) -> None:
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert _SECRET not in captured.out
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": "1.0",
        "status": "failed",
        "command": command,
        "error": {"code": code, "message": message},
    }


def test_explicit_json_parse_error_is_one_sanitized_object(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_path = tmp_path / _SECRET

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "lookup",
                "fi",
                "G06F3/048",
                "--json",
                "--unexpected",
                str(secret_path),
            ]
        )

    assert raised.value.code == 2
    _assert_json_error(
        capsys.readouterr(),
        command="lookup",
        code="ARGUMENT_ERROR",
        message="invalid command arguments",
    )


def test_always_json_command_parse_error_is_structured_without_json_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_path = tmp_path / _SECRET

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "build",
                str(tmp_path),
                "--release",
                "JPPM2099001",
                "--output",
                str(tmp_path / "out.sqlite"),
                "--unexpected",
                str(secret_path),
            ]
        )

    assert raised.value.code == 2
    _assert_json_error(
        capsys.readouterr(),
        command="build",
        code="ARGUMENT_ERROR",
        message="invalid command arguments",
    )


@pytest.mark.parametrize(
    ("handler", "argv", "error_factory", "code", "message"),
    [
        (
            "_run_build",
            ["build", ".", "--release", "JPPM2099001", "--output", "out.sqlite"],
            lambda: BuildError(f"build failed at /tmp/{_SECRET}"),
            "BUILD_FAILED",
            "PMGS build failed",
        ),
        (
            "_run_export_public",
            [
                "export-public",
                "--db",
                "database.sqlite",
                "--policy",
                "policy.yml",
                "--output",
                "public",
                "--base-url",
                "https://example.invalid",
            ],
            lambda: OSError(f"cannot write /tmp/{_SECRET}"),
            "IO_ERROR",
            "filesystem operation failed",
        ),
        (
            "_run_lookup",
            ["lookup", "fi", "G06F3/048", "--json"],
            lambda: CurrentPointerError(f"invalid pointer /tmp/{_SECRET}"),
            "CURRENT_POINTER_ERROR",
            "current PMGS database is unavailable",
        ),
        (
            "_run_search",
            ["search", "example", "--json"],
            lambda: sqlite3.DatabaseError(f"malformed database /tmp/{_SECRET}"),
            "DATABASE_ERROR",
            "PMGS database operation failed",
        ),
        (
            "_run_doctor",
            ["doctor", "--json"],
            lambda: RuntimeError(f"pointer changed at /tmp/{_SECRET}"),
            "RUNTIME_ERROR",
            "runtime operation failed",
        ),
    ],
)
def test_runtime_failures_use_stable_sanitized_json_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    handler: str,
    argv: list[str],
    error_factory: Callable[[], BaseException],
    code: str,
    message: str,
) -> None:
    def crash(_: object) -> int:
        raise error_factory()

    monkeypatch.setattr(cli_module, handler, crash)

    result = main(argv)

    assert result == 1
    _assert_json_error(
        capsys.readouterr(),
        command=argv[0],
        code=code,
        message=message,
    )


def test_missing_file_in_always_json_validate_uses_the_common_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / _SECRET / "missing.sqlite"

    result = main(["validate", str(missing)])

    assert result == 1
    _assert_json_error(
        capsys.readouterr(),
        command="validate",
        code="FILE_NOT_FOUND",
        message="requested file was not found",
    )


def test_human_mode_keeps_readable_stderr_and_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def crash(_: object) -> int:
        raise RuntimeError("human readable failure")

    monkeypatch.setattr(cli_module, "_run_lookup", crash)

    with pytest.raises(SystemExit) as raised:
        main(["lookup", "fi", "G06F3/048"])

    captured = capsys.readouterr()
    assert raised.value.code == 1
    assert captured.out == ""
    assert captured.err == "error: human readable failure\n"
