from __future__ import annotations

import json
import sqlite3
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


def test_end_of_options_marker_keeps_literal_json_query_in_human_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_data = tmp_path / "missing-data"

    with pytest.raises(SystemExit) as error:
        main(["search", "--data-dir", str(missing_data), "--", "--json"])

    assert error.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error:")
    assert not captured.err.lstrip().startswith("{")


def test_doctor_invalid_timeout_is_an_argument_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "doctor",
                "--db",
                str(tmp_path / "unused.sqlite"),
                "--timeout-seconds",
                "0",
                "--json",
            ]
        )

    assert error.value.code == 2
    _failure_payload(capsys, command="doctor", code="ARGUMENT_ERROR")


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


def test_unsupported_database_is_structured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "private" / "unsupported.sqlite"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.commit()
    finally:
        connection.close()

    result = main(["lookup", "fi", "G06F", "--db", str(database), "--json"])

    assert result == 1
    payload = _failure_payload(capsys, command="lookup", code="UNSUPPORTED_DATABASE")
    assert str(database) not in json.dumps(payload, ensure_ascii=False)


def test_corrupt_sqlite_is_mapped_for_query_and_validation_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "private" / "corrupt.sqlite"
    database.parent.mkdir()
    database.write_bytes(b"not a sqlite database")

    query_result = main(["lookup", "fi", "G06F", "--db", str(database), "--json"])

    assert query_result == 1
    query_payload = _failure_payload(
        capsys,
        command="lookup",
        code="UNSUPPORTED_DATABASE",
    )
    assert str(database) not in json.dumps(query_payload, ensure_ascii=False)

    validation_result = main(["validate", str(database)])

    assert validation_result == 1
    validation_payload = _failure_payload(
        capsys,
        command="validate",
        code="VALIDATION_FAILED",
    )
    assert str(database) not in json.dumps(validation_payload, ensure_ascii=False)


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


def test_build_failure_is_structured_and_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = str(tmp_path / "private" / "build-input")

    def fail_build(*args: object, **kwargs: object) -> object:
        raise cli_module.BuildError(f"build failed at {secret}")

    monkeypatch.setattr(cli_module, "build_database", fail_build)

    result = main(
        [
            "build",
            secret,
            "--release",
            "JPPM2099001",
            "--output",
            str(tmp_path / "output.sqlite"),
        ]
    )

    assert result == 1
    payload = _failure_payload(capsys, command="build", code="BUILD_FAILED")
    assert secret not in json.dumps(payload, ensure_ascii=False)


def test_validation_failure_is_one_envelope_with_structured_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidValidation:
        valid = False

        def as_dict(self) -> dict[str, object]:
            return {
                "schema_version": "2.0",
                "valid": False,
                "checks": {"required_tables": {"match": False}},
            }

    monkeypatch.setattr(cli_module, "validate_database", lambda _: InvalidValidation())

    result = main(["validate", str(tmp_path / "candidate.sqlite")])

    assert result == 1
    payload = _failure_payload(capsys, command="validate", code="VALIDATION_FAILED")
    assert payload["details"] == InvalidValidation().as_dict()


def test_public_export_failure_is_structured_and_sanitized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = str(tmp_path / "private" / "policy.json")

    def fail_export(*args: object, **kwargs: object) -> object:
        raise OSError(f"cannot read {secret}")

    monkeypatch.setattr(cli_module, "export_public", fail_export)

    result = main(
        [
            "export-public",
            "--db",
            str(tmp_path / "source.sqlite"),
            "--policy",
            secret,
            "--output",
            str(tmp_path / "output"),
            "--base-url",
            "https://example.invalid/pmgs",
        ]
    )

    assert result == 1
    payload = _failure_payload(capsys, command="export-public", code="PUBLIC_EXPORT_FAILED")
    assert secret not in json.dumps(payload, ensure_ascii=False)


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


def test_unexpected_json_runtime_error_does_not_emit_a_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = str(tmp_path / "private" / "unexpected")

    def fail_search(*args: object, **kwargs: object) -> object:
        raise RuntimeError(f"unexpected failure at {secret}")

    monkeypatch.setattr(cli_module, "_run_search", fail_search)

    result = main(["search", "query", "--db", str(tmp_path / "unused.sqlite"), "--json"])

    assert result == 1
    payload = _failure_payload(capsys, command="search", code="INTERNAL_ERROR")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert secret not in serialized
    assert "traceback" not in serialized.lower()
