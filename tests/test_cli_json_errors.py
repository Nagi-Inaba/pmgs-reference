from __future__ import annotations

import json
from pathlib import Path

import pytest

import pmgs_reference.cli as cli_module
from pmgs_reference.cli import main


def _failure_payload(
    capsys: pytest.CaptureFixture[str],
    *,
    command: str,
    code: str,
) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "failed"
    assert payload["command"] == command
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["message"]
    return payload


def test_json_argument_error_is_one_sanitized_object(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rejected = str(tmp_path / "private" / "credential-value")

    with pytest.raises(SystemExit) as error:
        main(
            [
                "lookup",
                "fi",
                "G06F",
                "--language",
                rejected,
                "--json",
            ]
        )

    assert error.value.code == 2
    payload = _failure_payload(capsys, command="lookup", code="ARGUMENT_ERROR")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert rejected not in serialized
    assert "credential-value" not in serialized


def test_always_json_command_argument_error_uses_the_same_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(["build", "source", "--release", "JPPM2099001"])

    assert error.value.code == 2
    _failure_payload(capsys, command="build", code="ARGUMENT_ERROR")


def test_json_file_not_found_is_returned_without_the_local_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "private" / "missing.sqlite"

    result = main(["lookup", "fi", "G06F", "--db", str(missing), "--json"])

    assert result == 1
    payload = _failure_payload(capsys, command="lookup", code="FILE_NOT_FOUND")
    assert str(missing) not in json.dumps(payload, ensure_ascii=False)


def test_always_json_runtime_error_is_structured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "private" / "missing.sqlite"

    result = main(["validate", str(missing)])

    assert result == 1
    payload = _failure_payload(capsys, command="validate", code="FILE_NOT_FOUND")
    assert str(missing) not in json.dumps(payload, ensure_ascii=False)


def test_invalid_current_pointer_is_structured_for_non_setup_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "private-data"
    state = data_root / "state"
    state.mkdir(parents=True)
    (state / "current.json").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")

    result = main(["lookup", "fi", "G06F", "--data-dir", str(data_root), "--json"])

    assert result == 1
    payload = _failure_payload(
        capsys,
        command="lookup",
        code="CURRENT_POINTER_INVALID",
    )
    assert str(data_root) not in json.dumps(payload, ensure_ascii=False)


def test_query_errors_use_the_common_failure_envelope(
    synthetic_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "lookup",
            "fi",
            "G06F",
            "--db",
            str(synthetic_database),
            "--relation-limit",
            "0",
            "--json",
        ]
    )

    assert result == 1
    _failure_payload(capsys, command="lookup", code="INVALID_RELATION_LIMIT")


def test_doctor_runtime_race_is_structured_and_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = str(tmp_path / "private" / "current.json")

    def fail_doctor(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"current pointer changed at {secret}")

    monkeypatch.setattr(cli_module, "doctor_database", fail_doctor)

    result = main(["doctor", "--db", str(tmp_path / "unused.sqlite"), "--json"])

    assert result == 1
    payload = _failure_payload(
        capsys,
        command="doctor",
        code="RUNTIME_STATE_CHANGED",
    )
    serialized = json.dumps(payload, ensure_ascii=False)
    assert secret not in serialized
    assert "current.json" not in serialized
