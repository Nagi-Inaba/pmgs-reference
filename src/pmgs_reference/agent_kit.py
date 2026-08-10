"""Generate and install local Codex and Claude Code integration artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
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


@dataclass(frozen=True)
class AgentKitResult:
    """Measured paths and commands for one generated local agent kit."""

    output_dir: Path
    database: Path
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
    database: Path,
) -> list[str]:
    """Return the current official CLI shape for registering the stdio server."""
    server = [
        str(python_executable),
        "-m",
        "pmgs_reference.cli",
        "mcp",
        "--db",
        str(database),
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


def render_codex_config(python_executable: Path, database: Path) -> str:
    """Render a mergeable Codex config.toml fragment."""

    def quote(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    arguments = [
        "-m",
        "pmgs_reference.cli",
        "mcp",
        "--db",
        str(database),
    ]
    rendered_arguments = ", ".join(quote(value) for value in arguments)
    return (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f"command = {quote(python_executable)}\n"
        f"args = [{rendered_arguments}]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 30\n"
    )


def render_claude_config(python_executable: Path, database: Path) -> str:
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
                    "--db",
                    str(database),
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
    database: str | Path,
    output_dir: str | Path,
    *,
    python_executable: str | Path,
    clients: Sequence[AgentClient],
) -> AgentKitResult:
    """Create a non-destructive, import-ready local agent kit."""
    resolved_database = Path(database).expanduser().resolve()
    resolved_python = Path(python_executable).expanduser().resolve()
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

    store = PMGSStore.open(resolved_database)
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
                render_codex_config(resolved_python, resolved_database),
            )
            config_files.append(resolved_output / relative)
        if "claude" in normalized_clients:
            relative = Path("claude", ".mcp.json")
            _write_text(
                temporary / relative,
                render_claude_config(resolved_python, resolved_database),
            )
            config_files.append(resolved_output / relative)

        _copy_skill(temporary / "skill" / SKILL_NAME)
        commands = {
            client: registration_command(client, resolved_python, resolved_database)
            for client in normalized_clients
        }
        manifest = {
            "schema_version": "1.0",
            "server_name": MCP_SERVER_NAME,
            "release_id": release_id,
            "database": str(resolved_database),
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
        python_executable=resolved_python,
        release_id=release_id,
        clients=normalized_clients,
        config_files=tuple(config_files),
        registration_commands=commands,
    )


def _skill_target(client: AgentClient, home: Path) -> Path:
    if client == "codex":
        return home / ".agents" / "skills" / SKILL_NAME
    return home / ".claude" / "skills" / SKILL_NAME


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
            created.append(target)
            _copy_skill(target)
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
