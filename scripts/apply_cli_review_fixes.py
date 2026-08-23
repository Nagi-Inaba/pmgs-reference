from __future__ import annotations

from pathlib import Path


def apply() -> None:
    cli_path = Path("src/pmgs_reference/cli.py")
    cli_text = cli_path.read_text(encoding="utf-8")

    import_anchor = "import argparse\nimport json\nimport sys\n"
    replacement_imports = "import argparse\nimport json\nimport math\nimport sqlite3\nimport sys\n"
    if cli_text.count(import_anchor) != 1:
        raise SystemExit("CLI import anchor mismatch")
    cli_text = cli_text.replace(import_anchor, replacement_imports, 1)

    old_json_mode = """def _wants_json(argv: Sequence[str], command: str | None) -> bool:
    return command in _ALWAYS_JSON_COMMANDS or "--json" in argv
"""
    new_json_mode = """def _wants_json(argv: Sequence[str], command: str | None) -> bool:
    option_tokens = list(argv)
    if "--" in option_tokens:
        option_tokens = option_tokens[: option_tokens.index("--")]
    return command in _ALWAYS_JSON_COMMANDS or "--json" in option_tokens
"""
    if cli_text.count(old_json_mode) != 1:
        raise SystemExit("JSON-mode anchor mismatch")
    cli_text = cli_text.replace(old_json_mode, new_json_mode, 1)

    parser_anchor = "\n\nclass JapaneseArgumentParser(argparse.ArgumentParser):\n"
    parser_helper = """

def _positive_finite_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if value <= 0 or not math.isfinite(value):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return value


class JapaneseArgumentParser(argparse.ArgumentParser):
"""
    if cli_text.count(parser_anchor) != 1:
        raise SystemExit("argument type helper anchor mismatch")
    cli_text = cli_text.replace(parser_anchor, parser_helper, 1)

    timeout_anchor = """    doctor.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_DOCTOR_TIMEOUT_SECONDS,
"""
    timeout_replacement = """    doctor.add_argument(
        "--timeout-seconds",
        type=_positive_finite_float,
        default=DEFAULT_DOCTOR_TIMEOUT_SECONDS,
"""
    if cli_text.count(timeout_anchor) != 1:
        raise SystemExit("doctor timeout anchor mismatch")
    cli_text = cli_text.replace(timeout_anchor, timeout_replacement, 1)

    exception_anchor = """    except ValueError as exc:
        if json_mode:
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
"""
    replacement = """    except sqlite3.DatabaseError as exc:
        if json_mode:
            if command == "build":
                return _emit_failure(command, "BUILD_FAILED", "database build failed")
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
    except ValueError as exc:
        if json_mode:
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
"""
    if cli_text.count(exception_anchor) != 1:
        raise SystemExit("SQLite exception anchor mismatch")
    cli_text = cli_text.replace(exception_anchor, replacement, 1)
    cli_path.write_text(cli_text, encoding="utf-8")

    test_path = Path("tests/test_cli_json_errors.py")
    test_text = test_path.read_text(encoding="utf-8")
    old_timeout_test = """def test_doctor_invalid_timeout_is_an_argument_error(
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
"""
    new_timeout_test = """@pytest.mark.parametrize("rejected", ["0", "-1", "nan", "inf", "-inf"])
def test_doctor_invalid_timeout_is_an_argument_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rejected: str,
) -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "doctor",
                "--db",
                str(tmp_path / "unused.sqlite"),
                "--timeout-seconds",
                rejected,
                "--json",
            ]
        )

    assert error.value.code == 2
    _failure_payload(capsys, command="doctor", code="ARGUMENT_ERROR")
"""
    if test_text.count(old_timeout_test) != 1:
        raise SystemExit("doctor timeout test anchor mismatch")
    test_text = test_text.replace(old_timeout_test, new_timeout_test, 1)
    test_path.write_text(test_text, encoding="utf-8")


if __name__ == "__main__":
    apply()
