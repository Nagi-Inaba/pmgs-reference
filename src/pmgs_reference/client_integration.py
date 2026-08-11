"""Non-destructive Codex and Claude Code MCP registration adapters."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from pmgs_reference.agent_kit import (
    MCP_SERVER_NAME,
    AgentClient,
    claude_global_config_file,
    inspect_agent_skill,
    install_agent_skills,
    registration_command,
)
from pmgs_reference.store_types import JSONDict

ClientSelection = Literal["auto", "none", "codex", "claude", "both"]


@dataclass(frozen=True, slots=True)
class ClientTarget:
    """One selected client and its resolved executable, when available."""

    client: AgentClient
    executable: Path | None


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured process outcome; command output is never copied into setup reports."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Injectable client command runner used by setup and tests."""

    def run(self, executable: Path, arguments: Sequence[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    """Execute resolved executables, including Windows cmd/bat launchers."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, executable: Path, arguments: Sequence[str]) -> CommandResult:
        suffix = executable.suffix.lower()
        command: str | list[str]
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            try:
                command = windows_batch_command(executable, arguments)
            except ValueError:
                return CommandResult(1, "", "unsafe characters in Windows batch arguments")
        elif os.name == "nt" and suffix == ".ps1":
            return CommandResult(1, "", "PowerShell-only client launchers are unsupported")
        else:
            command = [str(executable), *arguments]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError):
            return CommandResult(1, "", "client command could not be executed")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


_WINDOWS_BATCH_META = re.compile(r"[\r\n\"&|<>^%!()]")


def windows_batch_command(executable: Path, arguments: Sequence[str]) -> str:
    """Build a fail-closed cmd.exe invocation for an npm-style batch launcher."""
    tokens = [str(executable), *arguments]
    if any(_WINDOWS_BATCH_META.search(token) for token in tokens):
        raise ValueError("Windows batch arguments contain shell metacharacters")
    command_processor = Path(os.environ.get("COMSPEC", "cmd.exe")).absolute()
    command_line = subprocess.list2cmdline(tokens)
    command_prefix = subprocess.list2cmdline([str(command_processor), "/d", "/v:off", "/s", "/c"])
    return f'{command_prefix} "{command_line}"'


def detect_client_targets(
    selection: ClientSelection,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[ClientTarget, ...]:
    """Resolve selected clients without executing or modifying them."""
    if selection not in {"auto", "none", "codex", "claude", "both"}:
        raise ValueError(f"unsupported client selection: {selection}")
    if selection == "none":
        return ()
    requested: tuple[AgentClient, ...]
    if selection in {"auto", "both"}:
        requested = ("codex", "claude")
    else:
        requested = (cast(AgentClient, selection),)
    targets: list[ClientTarget] = []
    for client in requested:
        raw = which(client)
        executable = Path(raw).expanduser().absolute() if raw else None
        if executable is not None and os.name == "nt" and executable.suffix.lower() == ".ps1":
            executable = None
        if selection == "auto" and executable is None:
            continue
        targets.append(ClientTarget(client, executable))
    return tuple(targets)


def _same_path(first: object, second: Path) -> bool:
    if not isinstance(first, str):
        return False
    return os.path.normcase(os.path.abspath(os.path.expanduser(first))) == os.path.normcase(
        os.path.abspath(second)
    )


def _same_arguments(raw: object, expected: Sequence[str]) -> bool:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return False
    actual = cast(list[str], raw)
    if len(actual) != len(expected):
        return False
    for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
        if index == len(expected) - 1 and expected[index - 1] in {"--db", "--data-dir"}:
            if not _same_path(left, Path(right)):
                return False
        elif left != right:
            return False
    return True


def _config_matches(raw: object, python_executable: Path, data_dir: Path) -> bool:
    if not isinstance(raw, dict):
        return False
    config = cast(dict[str, object], raw)
    if not _same_path(config.get("command"), python_executable):
        return False
    expected_args = ["-m", "pmgs_reference.cli", "mcp", "--data-dir", str(data_dir)]
    return _same_arguments(config.get("args"), expected_args)


def _codex_server_state(
    executable: Path,
    python_executable: Path,
    data_dir: Path,
    runner: CommandRunner,
) -> tuple[str, str | None]:
    result = runner.run(executable, ("mcp", "list", "--json"))
    if result.returncode != 0:
        return "failed", f"Codex inspection failed with exit code {result.returncode}"
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "failed", "Codex returned invalid JSON while inspecting MCP servers"
    if not isinstance(raw, list):
        return "failed", "Codex returned an unexpected MCP server list"
    for item in raw:
        if not isinstance(item, dict) or item.get("name") != MCP_SERVER_NAME:
            continue
        transport = item.get("transport")
        if not isinstance(transport, dict) or transport.get("type") != "stdio":
            return "conflict", None
        return (
            ("matching", None)
            if _config_matches(transport, python_executable, data_dir)
            else ("conflict", None)
        )
    return "absent", None


def _claude_server_state(
    home: Path,
    python_executable: Path,
    data_dir: Path,
) -> tuple[str, str | None]:
    config_path = claude_global_config_file(home)
    if not config_path.exists():
        return "absent", None
    if not config_path.is_file():
        return "failed", "Claude user configuration is not a regular file"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "failed", "Claude user configuration could not be parsed"
    if not isinstance(raw, dict):
        return "failed", "Claude user configuration is not a JSON object"
    servers = raw.get("mcpServers")
    if servers is None:
        return "absent", None
    if not isinstance(servers, dict):
        return "failed", "Claude mcpServers configuration is invalid"
    config = servers.get(MCP_SERVER_NAME)
    if config is None:
        return "absent", None
    if not isinstance(config, dict) or config.get("type", "stdio") != "stdio":
        return "conflict", None
    return (
        ("matching", None)
        if _config_matches(config, python_executable, data_dir)
        else ("conflict", None)
    )


def _server_state(
    target: ClientTarget,
    python_executable: Path,
    data_dir: Path,
    home: Path,
    runner: CommandRunner,
) -> tuple[str, str | None]:
    assert target.executable is not None
    if target.client == "codex":
        return _codex_server_state(target.executable, python_executable, data_dir, runner)
    return _claude_server_state(home, python_executable, data_dir)


def integrate_clients(
    targets: Sequence[ClientTarget],
    approved_clients: Sequence[AgentClient],
    *,
    python_executable: Path,
    data_dir: Path,
    home: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> list[JSONDict]:
    """Reconcile approved clients without overwriting any conflicting state."""
    resolved_python = python_executable.expanduser().absolute()
    resolved_data_dir = data_dir.expanduser().resolve()
    resolved_home = Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    command_runner = runner or SubprocessCommandRunner()
    approved = frozenset(approved_clients)
    statuses: list[JSONDict] = []
    for target in targets:
        base: JSONDict = {
            "client": target.client,
            "executable": str(target.executable) if target.executable is not None else None,
            "status": "failed",
            "mcp": "not_checked",
            "skill": "not_checked",
            "restart_required": False,
            "error": None,
        }
        if target.executable is None:
            base["status"] = "not_detected"
            statuses.append(base)
            continue
        if target.client not in approved:
            base["status"] = "declined"
            statuses.append(base)
            continue
        skill = inspect_agent_skill(target.client, home=resolved_home)
        skill_status = str(skill["status"])
        base["skill"] = skill_status
        if skill_status == "conflict":
            base["status"] = "conflict"
            base["error"] = "a different pmgs-reference skill already exists"
            statuses.append(base)
            continue
        server_state, inspection_error = _server_state(
            target, resolved_python, resolved_data_dir, resolved_home, command_runner
        )
        base["mcp"] = server_state
        if server_state == "conflict":
            base["status"] = "conflict"
            base["error"] = "a different pmgs-reference MCP server already exists"
            statuses.append(base)
            continue
        if server_state == "failed":
            base["status"] = "failed"
            base["error"] = inspection_error or "client configuration inspection failed"
            statuses.append(base)
            continue
        changed = False
        if server_state == "absent":
            command = registration_command(
                target.client,
                resolved_python,
                data_dir=resolved_data_dir,
            )
            result = command_runner.run(target.executable, command[1:])
            if result.returncode != 0:
                base["status"] = "failed"
                base["error"] = f"registration failed with exit code {result.returncode}"
                statuses.append(base)
                continue
            verified, verification_error = _server_state(
                target, resolved_python, resolved_data_dir, resolved_home, command_runner
            )
            if verified != "matching":
                base["status"] = "failed"
                base["error"] = (
                    verification_error or "client did not retain the expected MCP server"
                )
                statuses.append(base)
                continue
            base["mcp"] = "installed"
            changed = True
        else:
            base["mcp"] = "already_present"
        if skill_status == "missing":
            try:
                installed = install_agent_skills((target.client,), home=resolved_home)
            except FileExistsError:
                base["status"] = "conflict"
                base["error"] = "a different pmgs-reference skill appeared during setup"
                statuses.append(base)
                continue
            except OSError:
                base["status"] = "failed"
                base["error"] = "the pmgs-reference skill could not be installed"
                statuses.append(base)
                continue
            base["skill"] = str(installed[0]["status"])
            changed = True
        else:
            base["skill"] = "already_present"
        base["status"] = "installed" if changed else "already_present"
        base["restart_required"] = changed
        statuses.append(base)
    return statuses
