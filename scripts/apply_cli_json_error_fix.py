from __future__ import annotations

from pathlib import Path


HELPERS = '''_COMMANDS = frozenset(
    {
        "inventory",
        "build",
        "setup",
        "validate",
        "lookup",
        "search",
        "document",
        "mcp",
        "doctor",
        "agent-kit",
        "install-agent-skill",
        "export-public",
        "validate-public",
        "audit-public",
    }
)
_ALWAYS_JSON_COMMANDS = frozenset(
    {
        "inventory",
        "build",
        "validate",
        "agent-kit",
        "install-agent-skill",
        "export-public",
        "validate-public",
        "audit-public",
    }
)


def _command_hint(argv: Sequence[str]) -> str | None:
    return next((token for token in argv if token in _COMMANDS), None)


def _wants_json(argv: Sequence[str], command: str | None) -> bool:
    return command in _ALWAYS_JSON_COMMANDS or "--json" in argv


def _failure_payload(
    command: str | None,
    code: str,
    message: str,
    *,
    details: JSONDict | None = None,
) -> JSONDict:
    payload: JSONDict = {
        "schema_version": "1.0",
        "status": "failed",
        "command": command,
        "error": {"code": code, "message": message},
    }
    if details is not None:
        payload["details"] = details
    return payload


def _emit_failure(
    command: str | None,
    code: str,
    message: str,
    exit_code: int = 1,
    *,
    details: JSONDict | None = None,
) -> int:
    _json_output(
        _failure_payload(
            command,
            code,
            message,
            details=details,
        )
    )
    return exit_code


def _safe_query_message(code: str) -> str:
    if code.startswith("INVALID_"):
        return "invalid query arguments"
    if code in {"RELEASE_NOT_FOUND", "EDITION_NOT_FOUND", "DOCUMENT_NOT_FOUND"}:
        return "requested record was not found"
    if code == "DATABASE_SCHEMA_UPGRADE_REQUIRED":
        return "database schema upgrade is required"
    if code == "RESPONSE_TOO_LARGE":
        return "structured response exceeds the configured limit"
    if code == "MULTIPLE_ACTIVE_REVISIONS":
        return "multiple revisions are active at the reference date"
    return "query operation failed"


def _value_error_code(command: str) -> tuple[str, str]:
    if command in {
        "lookup",
        "search",
        "document",
        "doctor",
        "mcp",
        "agent-kit",
    }:
        return "UNSUPPORTED_DATABASE", "database is not supported"
    if command == "validate":
        return "VALIDATION_FAILED", "database validation failed"
    if command in {"export-public", "validate-public", "audit-public"}:
        return "PUBLIC_OPERATION_FAILED", "public export operation failed"
    return "INVALID_STATE", "invalid local state"


'''

PARSER_CLASS = '''class JapaneseArgumentParser(argparse.ArgumentParser):
    """Keep Japanese help while supporting sanitized machine-readable errors."""

    def __init__(
        self,
        *args: object,
        json_mode: bool = False,
        command_hint: str | None = None,
        **kwargs: object,
    ) -> None:
        self.json_mode = json_mode
        self.command_hint = command_hint
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def format_help(self) -> str:
        text = super().format_help()
        for original, translated in (
            ("usage:", "使い方:"),
            ("positional arguments:", "位置引数:"),
            ("options:", "オプション:"),
            ("show this help message and exit", "このヘルプを表示して終了"),
        ):
            text = text.replace(original, translated)
        return text

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "使い方:", 1)

    def error(self, message: str) -> Never:
        if self.json_mode:
            _json_output(
                _failure_payload(
                    self.command_hint,
                    "ARGUMENT_ERROR",
                    "invalid command arguments",
                )
            )
            self.exit(2)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: エラー: {message}\n")


'''

OLD_CLASS = '''class JapaneseArgumentParser(argparse.ArgumentParser):
    """Keep the canonical CLI help headings and error prefix in Japanese."""

    def format_help(self) -> str:
        text = super().format_help()
        for original, translated in (
            ("usage:", "使い方:"),
            ("positional arguments:", "位置引数:"),
            ("options:", "オプション:"),
            ("show this help message and exit", "このヘルプを表示して終了"),
        ):
            text = text.replace(original, translated)
        return text

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "使い方:", 1)

    def error(self, message: str) -> Never:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: エラー: {message}\n")


'''

OLD_PARSER_HEAD = '''def _build_parser() -> argparse.ArgumentParser:
    parser = JapaneseArgumentParser(
        prog="pmgs", description="PMGS Referenceの構築と読み取り専用照会"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
'''

NEW_PARSER_HEAD = '''def _build_parser(
    *,
    json_mode: bool = False,
    command_hint: str | None = None,
) -> argparse.ArgumentParser:
    class SelectedArgumentParser(JapaneseArgumentParser):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(
                *args,
                json_mode=json_mode,
                command_hint=command_hint,
                **kwargs,
            )

    parser = SelectedArgumentParser(
        prog="pmgs", description="PMGS Referenceの構築と読み取り専用照会"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=SelectedArgumentParser,
    )
'''

OLD_VALIDATE = '''def _run_validate(args: argparse.Namespace) -> int:
    result = validate_database(args.database)
    if args.report is not None:
        write_validation_report(result, args.report)
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0 if result.valid else 1
'''

NEW_VALIDATE = '''def _run_validate(args: argparse.Namespace) -> int:
    result = validate_database(args.database)
    if args.report is not None:
        write_validation_report(result, args.report)
    if not result.valid:
        return _emit_failure(
            "validate",
            "VALIDATION_FAILED",
            "database validation failed",
            details=cast(JSONDict, result.as_dict()),
        )
    _json_output(cast(JSONDict, result.as_dict()))
    return 0
'''

OLD_MAIN = '''def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "build":
            return _run_build(args)
        if args.command == "setup":
            return _run_setup(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "lookup":
            return _run_lookup(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "document":
            return _run_document(args)
        if args.command == "mcp":
            run_stdio(args.db, data_dir=args.data_dir)
            return 0
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "agent-kit":
            return _run_agent_kit(args)
        if args.command == "install-agent-skill":
            return _run_install_agent_skill(args)
        if args.command == "export-public":
            return _run_export_public(args)
        if args.command == "validate-public":
            return _run_validate_public(args)
        if args.command == "audit-public":
            return _run_audit_public(args)
    except SetupUsageError as exc:
        if getattr(args, "json", False):
            _json_output(
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "error": {"code": "SETUP_USAGE", "message": str(exc)},
                }
            )
            return 2
        parser.error(str(exc))
    except (SetupOperationError, CurrentPointerError) as exc:
        if args.command == "setup" and getattr(args, "json", False):
            _json_output(
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "error": {"code": "SETUP_FAILED", "message": str(exc)},
                }
            )
            return 1
        parser.exit(1, f"error: {exc}\n")
    except PMGSQueryError as exc:
        if getattr(args, "json", False):
            _json_output({"error": {"code": exc.code, "message": exc.message}})
            return 1
        parser.exit(1, f"error [{exc.code}]: {exc.message}\n")
    except (BuildError, OSError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")
    parser.error(f"unsupported command: {args.command}")
    return 2
'''

NEW_MAIN = '''def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    command_hint = _command_hint(arguments)
    json_mode = _wants_json(arguments, command_hint)
    parser = _build_parser(json_mode=json_mode, command_hint=command_hint)
    args = parser.parse_args(arguments)
    command = str(args.command)
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        if args.command == "build":
            return _run_build(args)
        if args.command == "setup":
            return _run_setup(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "lookup":
            return _run_lookup(args)
        if args.command == "search":
            return _run_search(args)
        if args.command == "document":
            return _run_document(args)
        if args.command == "mcp":
            run_stdio(args.db, data_dir=args.data_dir)
            return 0
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "agent-kit":
            return _run_agent_kit(args)
        if args.command == "install-agent-skill":
            return _run_install_agent_skill(args)
        if args.command == "export-public":
            return _run_export_public(args)
        if args.command == "validate-public":
            return _run_validate_public(args)
        if args.command == "audit-public":
            return _run_audit_public(args)
    except SetupUsageError as exc:
        if json_mode:
            return _emit_failure(command, "SETUP_USAGE", "invalid setup options", 2)
        parser.error(str(exc))
    except CurrentPointerError as exc:
        if json_mode:
            return _emit_failure(
                command,
                "CURRENT_POINTER_INVALID",
                "managed current pointer is invalid",
            )
        parser.exit(1, f"error: {exc}\n")
    except SetupOperationError as exc:
        if json_mode:
            return _emit_failure(command, "SETUP_FAILED", "setup operation failed")
        parser.exit(1, f"error: {exc}\n")
    except PMGSQueryError as exc:
        if json_mode:
            return _emit_failure(command, exc.code, _safe_query_message(exc.code))
        parser.exit(1, f"error [{exc.code}]: {exc.message}\n")
    except FileNotFoundError as exc:
        if json_mode:
            return _emit_failure(
                command,
                "FILE_NOT_FOUND",
                "required file or directory was not found",
            )
        parser.exit(1, f"error: {exc}\n")
    except PermissionError as exc:
        if json_mode:
            return _emit_failure(command, "PERMISSION_DENIED", "permission denied")
        parser.exit(1, f"error: {exc}\n")
    except BuildError as exc:
        if json_mode:
            return _emit_failure(command, "BUILD_FAILED", "database build failed")
        parser.exit(1, f"error: {exc}\n")
    except RuntimeError as exc:
        if json_mode:
            if command == "doctor":
                return _emit_failure(
                    command,
                    "RUNTIME_STATE_CHANGED",
                    "runtime state changed during diagnostics",
                )
            return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
        raise
    except OSError as exc:
        if json_mode:
            if command == "export-public":
                return _emit_failure(
                    command,
                    "PUBLIC_EXPORT_FAILED",
                    "public export failed",
                )
            return _emit_failure(command, "IO_ERROR", "I/O operation failed")
        parser.exit(1, f"error: {exc}\n")
    except ValueError as exc:
        if json_mode:
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\n")
    except Exception:
        if json_mode:
            return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
        raise
    parser.error(f"unsupported command: {args.command}")
    return 2
'''


def apply() -> None:
    path = Path("src/pmgs_reference/cli.py")
    text = path.read_text(encoding="utf-8")

    if "def _failure_payload(" not in text:
        anchor = "class JapaneseArgumentParser(argparse.ArgumentParser):\n"
        if text.count(anchor) != 1:
            raise SystemExit("helper insertion anchor mismatch")
        text = text.replace(anchor, HELPERS + anchor, 1)

    if text.count(OLD_CLASS) != 1:
        raise SystemExit("parser class anchor mismatch")
    text = text.replace(OLD_CLASS, PARSER_CLASS, 1)

    if text.count(OLD_PARSER_HEAD) != 1:
        raise SystemExit("parser head anchor mismatch")
    text = text.replace(OLD_PARSER_HEAD, NEW_PARSER_HEAD, 1)

    if text.count(OLD_VALIDATE) != 1:
        raise SystemExit("validate anchor mismatch")
    text = text.replace(OLD_VALIDATE, NEW_VALIDATE, 1)

    if text.count(OLD_MAIN) != 1:
        raise SystemExit("main anchor mismatch")
    text = text.replace(OLD_MAIN, NEW_MAIN, 1)

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    apply()
