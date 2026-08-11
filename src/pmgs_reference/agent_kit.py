"""Generate and install local Codex and Claude Code integration artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final, Literal, cast

from pmgs_reference.store import JSONDict, JSONValue, PMGSStore

type AgentClient = Literal["codex", "claude"]

MCP_SERVER_NAME: Final = "pmgs-reference"
SKILL_NAME: Final = "pmgs-reference"
SUPPORTED_AGENT_CLIENTS: Final[tuple[AgentClient, ...]] = ("codex", "claude")


def claude_config_directory(
    home: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve Claude's user configuration directory, including custom profiles."""
    current_environ = os.environ if environ is None else environ
    configured = current_environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser().absolute()
    return home / ".claude"


def claude_global_config_file(
    home: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the user-scoped Claude MCP configuration file."""
    current_environ = os.environ if environ is None else environ
    configured = current_environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return claude_config_directory(home, environ=current_environ) / ".claude.json"
    return home / ".claude.json"


@dataclass(frozen=True)
class AgentKitResult:
    """Measured paths and commands for one generated local agent kit."""

    output_dir: Path
    database: Path
    data_dir: Path | None
    python_executable: Path
    release_id: str
    clients: tuple[AgentClient, ...]
    config_files: tuple[Path, ...]
    registration_commands: dict[AgentClient, list[str]]

    def as_dict(self) -> JSONDict:
        return {
            "schema_version": "1.0",
            "output_dir": str(self.output_dir),
            "database": str(self.database),
            "data_dir": str(self.data_dir) if self.data_dir is not None else None,
            "python_executable": str(self.python_executable),
            "release_id": self.release_id,
            "clients": list(self.clients),
            "config_files": [str(path) for path in self.config_files],
            "skill_directory": str(self.output_dir / "skill" / SKILL_NAME),
            "registration_commands": cast(dict[str, JSONValue], self.registration_commands),
        }


def resolve_clients(client: str) -> tuple[AgentClient, ...]:
    """Resolve the CLI's codex, claude, or both selector."""
    if client == "both":
        return ("codex", "claude")
    if client in SUPPORTED_AGENT_CLIENTS:
        return (client,)
    raise ValueError(f"unsupported agent client: {client}")


def registration_command(
    client: AgentClient,
    python_executable: Path,
    database: Path | None = None,
    *,
    data_dir: Path | None = None,
) -> list[str]:
    """Return the current official CLI shape for registering the stdio server."""
    locator = _database_locator_args(database, data_dir=data_dir)
    server = [
        str(python_executable),
        "-m",
        "pmgs_reference.cli",
        "mcp",
        *locator,
    ]
    if client == "codex":
        return ["codex", "mcp", "add", MCP_SERVER_NAME, "--", *server]
    return [
        "claude",
        "mcp",
        "add",
        "--transport",
        "stdio",
        "--scope",
        "user",
        MCP_SERVER_NAME,
        "--",
        *server,
    ]


def _database_locator_args(database: Path | None, *, data_dir: Path | None) -> list[str]:
    if (database is None) == (data_dir is None):
        raise ValueError("exactly one of database or data_dir is required")
    if data_dir is not None:
        return ["--data-dir", str(data_dir)]
    assert database is not None
    return ["--db", str(database)]


def render_codex_config(
    python_executable: Path,
    database: Path | None = None,
    *,
    data_dir: Path | None = None,
) -> str:
    """Render a mergeable Codex config.toml fragment."""

    def quote(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    arguments = [
        "-m",
        "pmgs_reference.cli",
        "mcp",
        *_database_locator_args(database, data_dir=data_dir),
    ]
    rendered_arguments = ", ".join(quote(value) for value in arguments)
    return (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f"command = {quote(python_executable)}\n"
        f"args = [{rendered_arguments}]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 30\n"
    )


def render_claude_config(
    python_executable: Path,
    database: Path | None = None,
    *,
    data_dir: Path | None = None,
) -> str:
    """Render a Claude Code project-scoped .mcp.json document."""
    payload = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "type": "stdio",
                "command": str(python_executable),
                "args": [
                    "-m",
                    "pmgs_reference.cli",
                    "mcp",
                    *_database_locator_args(database, data_dir=data_dir),
                ],
            }
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _skill_resource() -> Traversable:
    return files("pmgs_reference").joinpath("resources", "skills", SKILL_NAME)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest().upper()


def _copy_skill(target: Path) -> None:
    resource = _skill_resource()
    with as_file(resource) as source:
        shutil.copytree(source, target)


def _resource_skill_sha256() -> str:
    resource = _skill_resource()
    with as_file(resource) as source:
        return _tree_sha256(source)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def prepare_agent_kit(
    database: str | Path | None,
    output_dir: str | Path,
    *,
    python_executable: str | Path,
    clients: Sequence[AgentClient],
    data_dir: str | Path | None = None,
) -> AgentKitResult:
    """Create a non-destructive, import-ready local agent kit."""
    if database is not None and data_dir is not None:
        raise ValueError("database and data_dir are mutually exclusive")
    resolved_data_dir = Path(data_dir).expanduser().resolve() if data_dir is not None else None
    store = PMGSStore.open(database, data_dir=resolved_data_dir)
    resolved_database = store.path
    # Keep a virtual environment's interpreter path intact. On POSIX, resolving
    # the symlink can escape the environment and lose its installed packages.
    resolved_python = Path(python_executable).expanduser().absolute()
    resolved_output = Path(output_dir).expanduser().resolve()
    if not resolved_python.is_file():
        raise FileNotFoundError(f"Python executable not found: {resolved_python}")
    if resolved_output.exists():
        raise FileExistsError(f"agent kit output already exists: {resolved_output}")

    normalized_clients = tuple(dict.fromkeys(clients))
    if not normalized_clients or any(
        item not in SUPPORTED_AGENT_CLIENTS for item in normalized_clients
    ):
        raise ValueError("clients must contain codex and/or claude")

    release_id = str(store.release_info()["release_id"])
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{resolved_output.name}-", dir=resolved_output.parent)
    )
    try:
        config_files: list[Path] = []
        if "codex" in normalized_clients:
            relative = Path("codex", "config.toml")
            _write_text(
                temporary / relative,
                render_codex_config(
                    resolved_python,
                    resolved_database if resolved_data_dir is None else None,
                    data_dir=resolved_data_dir,
                ),
            )
            config_files.append(resolved_output / relative)
        if "claude" in normalized_clients:
            relative = Path("claude", ".mcp.json")
            _write_text(
                temporary / relative,
                render_claude_config(
                    resolved_python,
                    resolved_database if resolved_data_dir is None else None,
                    data_dir=resolved_data_dir,
                ),
            )
            config_files.append(resolved_output / relative)

        _copy_skill(temporary / "skill" / SKILL_NAME)
        commands = {
            client: registration_command(
                client,
                resolved_python,
                resolved_database if resolved_data_dir is None else None,
                data_dir=resolved_data_dir,
            )
            for client in normalized_clients
        }
        manifest = {
            "schema_version": "1.0",
            "server_name": MCP_SERVER_NAME,
            "release_id": release_id,
            "database": str(resolved_database),
            "data_dir": str(resolved_data_dir) if resolved_data_dir is not None else None,
            "python_executable": str(resolved_python),
            "clients": list(normalized_clients),
            "skill_sha256": _resource_skill_sha256(),
            "registration_commands": commands,
            "default_language": "ja",
            "supported_languages": ["ja", "en"],
            "notes": [
                "既存のクライアント設定を上書きせず、生成された設定をマージしてください。",
                "サーバーとスキルは読み取り専用であり、PMGSデータを自動取得しません。",
            ],
        }
        _write_text(
            temporary / "agent-kit.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        temporary.rename(resolved_output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return AgentKitResult(
        output_dir=resolved_output,
        database=resolved_database,
        data_dir=resolved_data_dir,
        python_executable=resolved_python,
        release_id=release_id,
        clients=normalized_clients,
        config_files=tuple(config_files),
        registration_commands=commands,
    )


def _skill_target(client: AgentClient, home: Path) -> Path:
    if client == "codex":
        return home / ".agents" / "skills" / SKILL_NAME
    return claude_config_directory(home) / "skills" / SKILL_NAME


def inspect_agent_skill(
    client: AgentClient,
    *,
    home: str | Path | None = None,
) -> JSONDict:
    """Inspect one managed skill without changing the user's files."""
    resolved_home = Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    target = _skill_target(client, resolved_home)
    expected_hash = _resource_skill_sha256()
    if not target.exists():
        status = "missing"
        actual_hash: str | None = None
    elif target.is_dir():
        actual_hash = _tree_sha256(target)
        status = "already_present" if actual_hash == expected_hash else "conflict"
    else:
        status = "conflict"
        actual_hash = None
    return {
        "client": client,
        "target": str(target),
        "status": status,
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
    }


def install_agent_skills(
    clients: Sequence[AgentClient],
    *,
    home: str | Path | None = None,
) -> list[JSONDict]:
    """Install the common skill without overwriting a different existing copy."""
    normalized_clients = tuple(dict.fromkeys(clients))
    if not normalized_clients or any(
        item not in SUPPORTED_AGENT_CLIENTS for item in normalized_clients
    ):
        raise ValueError("clients must contain codex and/or claude")
    resolved_home = Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    expected_hash = _resource_skill_sha256()
    targets = [(client, _skill_target(client, resolved_home)) for client in normalized_clients]

    statuses: list[JSONDict] = []
    for client, target in targets:
        if target.exists():
            if not target.is_dir() or _tree_sha256(target) != expected_hash:
                raise FileExistsError(f"different skill already exists: {target}")
            statuses.append(
                {
                    "client": client,
                    "target": str(target),
                    "status": "already_present",
                    "sha256": expected_hash,
                }
            )

    created: list[Path] = []
    try:
        for client, target in targets:
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_skill(target)
            # Only roll back a tree after copytree returned successfully. If a
            # different tree appeared concurrently, copytree raises before this
            # point and that external tree must be retained.
            created.append(target)
            if _tree_sha256(target) != expected_hash:
                raise OSError(f"installed skill hash mismatch: {target}")
            statuses.append(
                {
                    "client": client,
                    "target": str(target),
                    "status": "installed",
                    "sha256": expected_hash,
                }
            )
    except BaseException:
        for target in reversed(created):
            shutil.rmtree(target, ignore_errors=True)
        raise
    return sorted(statuses, key=lambda item: str(item["client"]))
