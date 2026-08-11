"""Local database and stdio MCP diagnostics for PMGS Reference."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from pmgs_reference.agent_kit import MCP_SERVER_NAME
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore

EXPECTED_MCP_TOOLS: Final = (
    "lookup_classification",
    "search_pmgs",
    "get_pmgs_document",
)


@dataclass(frozen=True)
class DoctorResult:
    """Structured outcome of one local PMGS integration diagnostic."""

    ok: bool
    database: Path
    database_sha256: str
    release: JSONDict
    checks: dict[str, bool]
    tool_names: tuple[str, ...]
    sample: JSONDict
    errors: tuple[str, ...]

    def as_dict(self) -> JSONDict:
        return {
            "schema_version": "1.0",
            "ok": self.ok,
            "database": str(self.database),
            "database_sha256": self.database_sha256,
            "release": self.release,
            "checks": cast(dict[str, JSONValue], self.checks),
            "tool_names": list(self.tool_names),
            "sample": self.sample,
            "errors": list(self.errors),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _sample_identity(database: Path) -> JSONDict:
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT scheme, normalized_code, edition FROM concept "
            "ORDER BY CASE scheme WHEN 'fi' THEN 0 WHEN 'fterm' THEN 1 ELSE 2 END, "
            "edition, normalized_code LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("PMGS Reference database contains no classifications")
    raw_edition = row["edition"]
    return {
        "scheme": str(row["scheme"]),
        "code": str(row["normalized_code"]),
        "edition": None if raw_edition in {None, ""} else str(raw_edition),
    }


async def _check_stdio(
    database: Path,
    python_executable: Path,
    sample: JSONDict,
    *,
    data_dir: Path | None = None,
) -> tuple[dict[str, bool], tuple[str, ...], JSONDict]:
    locator = ["--data-dir", str(data_dir)] if data_dir is not None else ["--db", str(database)]
    parameters = StdioServerParameters(
        command=str(python_executable),
        args=[
            "-m",
            "pmgs_reference.cli",
            "mcp",
            *locator,
        ],
    )
    arguments: dict[str, JSONValue] = {
        "scheme": sample["scheme"],
        "code": sample["code"],
        "language": "ja",
    }
    if sample["edition"] is not None:
        arguments["edition"] = sample["edition"]
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        lookup = await session.call_tool("lookup_classification", arguments)

    names = tuple(tool.name for tool in listed.tools)
    annotations_ok = all(
        tool.annotations is not None
        and tool.annotations.read_only_hint is True
        and tool.annotations.destructive_hint is False
        for tool in listed.tools
    )
    payload = cast(JSONDict, lookup.structured_content or {})
    sample_ok = payload.get("match_status") in {"exact", "normalized_exact"}
    checks = {
        "mcp_server_identity": initialized.server_info.name == MCP_SERVER_NAME,
        "mcp_tool_contract": names == EXPECTED_MCP_TOOLS,
        "mcp_tools_read_only": annotations_ok,
        "sample_lookup": sample_ok,
    }
    return checks, names, payload


def doctor_database(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
    python_executable: str | Path | None = None,
) -> DoctorResult:
    """Verify a database, real stdio handshake, read-only tools, and hash stability."""
    resolved_data_dir = Path(data_dir).expanduser().resolve() if data_dir is not None else None
    store = PMGSStore.open(database, data_dir=resolved_data_dir)
    resolved_database = store.path
    # Preserve the virtual-environment launcher instead of resolving its POSIX
    # symlink to a system interpreter that cannot import this package.
    resolved_python = Path(python_executable or sys.executable).expanduser().absolute()
    if not resolved_python.is_file():
        raise FileNotFoundError(f"Python executable not found: {resolved_python}")

    before = _sha256(resolved_database)
    release = store.release_info()
    sample_input = _sample_identity(resolved_database)
    errors: list[str] = []
    try:
        stdio_checks, tool_names, sample_output = asyncio.run(
            _check_stdio(
                resolved_database,
                resolved_python,
                sample_input,
                data_dir=resolved_data_dir,
            )
        )
    except Exception as exc:  # pragma: no cover - platform failures remain in the report
        stdio_checks = {
            "mcp_server_identity": False,
            "mcp_tool_contract": False,
            "mcp_tools_read_only": False,
            "sample_lookup": False,
        }
        tool_names = ()
        sample_output = {}
        errors.append(f"stdio MCP check failed: {type(exc).__name__}: {exc}")
    after = _sha256(resolved_database)
    checks = {
        "database_schema": True,
        "release_metadata": bool(release.get("release_id")),
        **stdio_checks,
        "database_unchanged": before == after,
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"check failed: {name}")
    return DoctorResult(
        ok=all(checks.values()),
        database=resolved_database,
        database_sha256=after,
        release=release,
        checks=checks,
        tool_names=tool_names,
        sample={"input": sample_input, "output": sample_output},
        errors=tuple(errors),
    )
