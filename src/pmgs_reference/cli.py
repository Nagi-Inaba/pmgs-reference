"""Stable CLI facade that preserves human output and sanitizes JSON failures."""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from pmgs_reference import cli_core as _core
from pmgs_reference.data_paths import CurrentPointerError
from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.ingest.build import BuildError
from pmgs_reference.setup import SetupOperationError, SetupUsageError
from pmgs_reference.store import JSONDict

JapaneseArgumentParser = _core.JapaneseArgumentParser
_build_parser = _core._build_parser
_json_output = _core._json_output
detect_client_targets = _core.detect_client_targets

_run_inventory = _core._run_inventory
_run_build = _core._run_build
_run_setup = _core._run_setup
_run_validate = _core._run_validate
_run_lookup = _core._run_lookup
_run_search = _core._run_search
_run_document = _core._run_document
_run_doctor = _core._run_doctor
_run_agent_kit = _core._run_agent_kit
_run_install_agent_skill = _core._run_install_agent_skill
_run_export_public = _core._run_export_public
_run_validate_public = _core._run_validate_public
_run_audit_public = _core._run_audit_public

_COMMANDS = frozenset(
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
_SYNC_NAMES = (
    "detect_client_targets",
    "_run_inventory",
    "_run_build",
    "_run_setup",
    "_run_validate",
    "_run_lookup",
    "_run_search",
    "_run_document",
    "_run_doctor",
    "_run_agent_kit",
    "_run_install_agent_skill",
    "_run_export_public",
    "_run_validate_public",
    "_run_audit_public",
)


def __getattr__(name: str) -> Any:
    """Preserve the historical module surface for callers and tests."""
    return getattr(_core, name)


def _sync_core_overrides() -> None:
    for name in _SYNC_NAMES:
        setattr(_core, name, globals()[name])


def _command_hint(argv: Sequence[str]) -> str | None:
    return next((token for token in argv if token in _COMMANDS), None)


def _json_mode(argv: Sequence[str], command: str | None) -> bool:
    return "--json" in argv or command in _ALWAYS_JSON_COMMANDS


def _emit_json_error(command: str | None, code: str, message: str) -> None:
    payload: JSONDict = {
        "schema_version": "1.0",
        "status": "failed",
        "command": command,
        "error": {"code": code, "message": message},
    }
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _error_contract(exc: BaseException) -> tuple[str, str, int] | None:
    if isinstance(exc, SetupUsageError):
        return "SETUP_USAGE", "invalid setup arguments", 2
    if isinstance(exc, CurrentPointerError):
        return "CURRENT_POINTER_ERROR", "current PMGS database is unavailable", 1
    if isinstance(exc, SetupOperationError):
        return "SETUP_FAILED", "PMGS setup failed", 1
    if isinstance(exc, PMGSQueryError):
        return exc.code, "PMGS query failed", 1
    if isinstance(exc, BuildError):
        return "BUILD_FAILED", "PMGS build failed", 1
    if isinstance(exc, FileNotFoundError):
        return "FILE_NOT_FOUND", "requested file was not found", 1
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED", "permission denied", 1
    if isinstance(exc, sqlite3.DatabaseError):
        return "DATABASE_ERROR", "PMGS database operation failed", 1
    if isinstance(exc, OSError):
        return "IO_ERROR", "filesystem operation failed", 1
    if isinstance(exc, ValueError):
        return "INVALID_VALUE", "invalid value", 1
    if isinstance(exc, RuntimeError):
        return "RUNTIME_ERROR", "runtime operation failed", 1
    return None


def _dispatch(args: argparse.Namespace) -> int:
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
        _core.run_stdio(args.db, data_dir=args.data_dir)
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
    raise ValueError("unsupported command")


def _replay(stdout: io.StringIO, stderr: io.StringIO) -> None:
    sys.stdout.write(stdout.getvalue())
    sys.stderr.write(stderr.getvalue())


def _run_json(argv: Sequence[str], command: str | None) -> int:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            args = _core._build_parser().parse_args(argv)
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 2
        if status == 0:
            _replay(stdout, stderr)
            raise
        _emit_json_error(command, "ARGUMENT_ERROR", "invalid command arguments")
        raise SystemExit(status) from None

    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = _dispatch(args)
    except BaseException as exc:
        contract = _error_contract(exc)
        if contract is None:
            raise
        code, message, status = contract
        _emit_json_error(command, code, message)
        return status

    _replay(stdout, stderr)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    command = _command_hint(raw_argv)
    _sync_core_overrides()
    if _json_mode(raw_argv, command):
        return _run_json(raw_argv, command)
    try:
        return _core.main(raw_argv)
    except (sqlite3.DatabaseError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    raise SystemExit(main())
