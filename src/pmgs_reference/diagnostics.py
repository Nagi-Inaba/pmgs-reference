"""Local database and stdio MCP diagnostics for PMGS Reference."""

from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from pmgs_reference.agent_kit import MCP_SERVER_NAME
from pmgs_reference.data_paths import resolve_database
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore

EXPECTED_MCP_TOOLS: Final = (
    "lookup_classification",
    "search_pmgs",
    "get_pmgs_document",
)
DEFAULT_DOCTOR_TIMEOUT_SECONDS: Final = 30.0


class DoctorTimeoutError(TimeoutError):
    """A bounded stdio diagnostic expired during a named stage."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"stdio MCP diagnostic timed out during {stage}")


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
    failure: JSONDict | None = None

    def as_dict(self) -> JSONDict:
        return {
            "schema_version": "2.0",
            "ok": self.ok,
            "database": str(self.database),
            "database_sha256": self.database_sha256,
            "release": self.release,
            "checks": cast(dict[str, JSONValue], self.checks),
            "tool_names": list(self.tool_names),
            "sample": self.sample,
            "errors": list(self.errors),
            "failure": self.failure,
        }


def _validate_timeout_seconds(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")


def _failed_stdio_checks() -> dict[str, bool]:
    return {
        "mcp_server_identity": False,
        "mcp_tool_contract": False,
        "mcp_tools_read_only": False,
        "sample_lookup": False,
        "sample_search": False,
        "sample_document": False,
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
        try:
            row = connection.execute(
                "SELECT c.scheme, c.normalized_code, c.edition, cr.version_indicator "
                "FROM concept c JOIN release r ON r.release_id = c.release_id "
                "JOIN concept_revision cr ON cr.concept_id = c.concept_id "
                "WHERE c.record_status = 'canonical' "
                "AND (cr.valid_from IS NULL OR cr.valid_from <= r.reference_date) "
                "AND (cr.valid_to IS NULL OR cr.valid_to >= r.reference_date) "
                "ORDER BY CASE c.scheme WHEN 'fi' THEN 0 WHEN 'fterm' THEN 1 ELSE 2 END, "
                "c.edition, c.normalized_code, cr.version_indicator LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            # Preserve the small helper's compatibility with isolated unit fixtures.
            row = connection.execute(
                "SELECT scheme, normalized_code, edition, NULL AS version_indicator "
                "FROM concept LIMIT 1"
            ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("PMGS Reference database contains no classifications")
    raw_edition = row["edition"]
    raw_version = row["version_indicator"]
    return {
        "scheme": str(row["scheme"]),
        "code": str(row["normalized_code"]),
        "edition": None if raw_edition in {None, ""} else str(raw_edition),
        "version": None if raw_version in {None, ""} else str(raw_version),
    }


def _search_sample(database: Path) -> str:
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT ct.text FROM concept_text ct "
            "JOIN concept_revision cr ON cr.revision_id = ct.revision_id "
            "JOIN concept c ON c.concept_id = cr.concept_id "
            "JOIN release r ON r.release_id = c.release_id "
            "WHERE c.record_status = 'canonical' AND ct.language = 'ja' "
            "AND trim(ct.text) != '' "
            "AND (cr.valid_from IS NULL OR cr.valid_from <= r.reference_date) "
            "AND (cr.valid_to IS NULL OR cr.valid_to >= r.reference_date) "
            "ORDER BY CASE c.scheme WHEN 'fi' THEN 0 WHEN 'fterm' THEN 1 ELSE 2 END, "
            "c.edition, c.normalized_code, cr.version_indicator, ct.sequence_number, ct.text_id "
            "LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("PMGS Reference database contains no searchable classification text")
    text = " ".join(str(row[0]).split())
    for term in text.split():
        if len(term) >= 3:
            return term[:64]
    return text[:64]


def _document_sample(database: Path) -> str:
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            "SELECT d.document_id FROM document d "
            "WHERE EXISTS (SELECT 1 FROM document_text dt WHERE dt.document_id = d.document_id) "
            "ORDER BY d.kind, d.document_id LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("PMGS Reference database contains no readable documents")
    return str(row[0])


async def _check_stdio(
    database: Path,
    python_executable: Path,
    sample: JSONDict,
    *,
    search_query: str,
    document_id: str,
    data_dir: Path | None = None,
    server_parameters: StdioServerParameters | None = None,
    stage: list[str] | None = None,
) -> tuple[dict[str, bool], tuple[str, ...], JSONDict]:
    def mark(value: str) -> None:
        if stage is not None:
            stage[0] = value

    locator = ["--data-dir", str(data_dir)] if data_dir is not None else ["--db", str(database)]
    parameters = server_parameters or StdioServerParameters(
        command=str(python_executable),
        args=[
            "-m",
            "pmgs_reference.cli",
            "mcp",
            *locator,
        ],
    )
    lookup_arguments: dict[str, JSONValue] = {
        "scheme": sample["scheme"],
        "code": sample["code"],
        "language": "ja",
    }
    if sample["edition"] is not None:
        lookup_arguments["edition"] = sample["edition"]
    if sample["version"] is not None:
        lookup_arguments["version"] = sample["version"]

    mark("stdio_start")
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        mark("initialize")
        initialized = await session.initialize()
        mark("list_tools")
        listed = await session.list_tools()
        mark("lookup_classification")
        lookup = await session.call_tool("lookup_classification", lookup_arguments)
        mark("search_pmgs")
        search = await session.call_tool(
            "search_pmgs",
            {
                "query": search_query,
                "content_types": ["classification"],
                "language": "ja",
                "limit": 1,
            },
        )
        mark("get_pmgs_document")
        document = await session.call_tool(
            "get_pmgs_document",
            {"document_id": document_id},
        )
        mark("shutdown")

    mark("complete")
    names = tuple(tool.name for tool in listed.tools)
    annotations_ok = all(
        tool.annotations is not None
        and tool.annotations.read_only_hint is True
        and tool.annotations.destructive_hint is False
        for tool in listed.tools
    )
    lookup_payload = cast(JSONDict, lookup.structured_content or {})
    search_payload = cast(JSONDict, search.structured_content or {})
    document_payload = cast(JSONDict, document.structured_content or {})
    lookup_ok = (
        not lookup.is_error
        and lookup_payload.get("schema_version") == "2.0"
        and lookup_payload.get("match_status") in {"exact", "normalized_exact"}
        and bool(lookup_payload.get("reference_date"))
    )
    search_groups = search_payload.get("results_by_type")
    classification_group = (
        search_groups.get("classification") if isinstance(search_groups, dict) else None
    )
    classification_count = (
        classification_group.get("count") if isinstance(classification_group, dict) else None
    )
    search_ok = (
        not search.is_error
        and search_payload.get("schema_version") == "2.0"
        and isinstance(classification_group, dict)
        and classification_group.get("requested") is True
        and isinstance(classification_count, int)
        and not isinstance(classification_count, bool)
        and classification_count >= 1
    )
    segments = document_payload.get("segments")
    sources = document_payload.get("sources")
    document_ok = (
        not document.is_error
        and document_payload.get("schema_version") == "2.0"
        and document_payload.get("document_id") == document_id
        and isinstance(segments, list)
        and len(segments) >= 1
        and isinstance(sources, list)
        and len(sources) >= 1
    )
    checks = {
        "mcp_server_identity": initialized.server_info.name == MCP_SERVER_NAME,
        "mcp_tool_contract": names == EXPECTED_MCP_TOOLS,
        "mcp_tools_read_only": annotations_ok,
        "sample_lookup": lookup_ok,
        "sample_search": search_ok,
        "sample_document": document_ok,
    }
    return (
        checks,
        names,
        {
            "lookup": lookup_payload,
            "search": search_payload,
            "document": document_payload,
        },
    )


async def _run_stdio_check(
    database: Path,
    python_executable: Path,
    sample: JSONDict,
    *,
    search_query: str,
    document_id: str,
    data_dir: Path | None = None,
    timeout_seconds: float = DEFAULT_DOCTOR_TIMEOUT_SECONDS,
    server_parameters: StdioServerParameters | None = None,
) -> tuple[dict[str, bool], tuple[str, ...], JSONDict]:
    """Run the complete stdio diagnostic within one cancellation boundary."""
    _validate_timeout_seconds(timeout_seconds)
    stage = ["stdio_start"]
    try:
        async with asyncio.timeout(timeout_seconds):
            return await _check_stdio(
                database,
                python_executable,
                sample,
                search_query=search_query,
                document_id=document_id,
                data_dir=data_dir,
                server_parameters=server_parameters,
                stage=stage,
            )
    except TimeoutError as exc:
        raise DoctorTimeoutError(stage[0]) from exc


def doctor_database(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
    python_executable: str | Path | None = None,
    timeout_seconds: float = DEFAULT_DOCTOR_TIMEOUT_SECONDS,
) -> DoctorResult:
    """Verify a database, all stdio tools, bounded runtime, and hash stability."""
    _validate_timeout_seconds(timeout_seconds)
    resolved_data_dir = Path(data_dir).expanduser().resolve() if data_dir is not None else None
    target = resolve_database(database, data_dir=resolved_data_dir)
    store = PMGSStore.open(database, data_dir=resolved_data_dir)
    resolved_database = store.path
    if resolved_database != target.path:
        raise RuntimeError("managed current.json changed while doctor was starting")
    # Preserve the virtual-environment launcher instead of resolving its POSIX
    # symlink to a system interpreter that cannot import this package.
    resolved_python = Path(python_executable or sys.executable).expanduser().absolute()
    if not resolved_python.is_file():
        raise FileNotFoundError(f"Python executable not found: {resolved_python}")

    before = _sha256(resolved_database)
    release = store.release_info()
    errors: list[str] = []
    failure: JSONDict | None = None
    sample_input: JSONDict = {}
    sample_output: JSONDict = {}
    tool_names: tuple[str, ...] = ()

    try:
        classification_sample = _sample_identity(resolved_database)
        search_query = _search_sample(resolved_database)
        document_id = _document_sample(resolved_database)
        sample_input = {
            **classification_sample,
            "search_query": search_query,
            "document_id": document_id,
        }
    except (OSError, sqlite3.Error, ValueError) as exc:
        stdio_checks = _failed_stdio_checks()
        failure = {
            "code": "SAMPLE_SELECTION_FAILED",
            "stage": "sample_selection",
            "message": "unable to select deterministic doctor samples",
        }
        errors.append(f"doctor sample selection failed: {type(exc).__name__}")
    else:
        try:
            stdio_checks, tool_names, sample_output = asyncio.run(
                _run_stdio_check(
                    resolved_database,
                    resolved_python,
                    classification_sample,
                    search_query=search_query,
                    document_id=document_id,
                    data_dir=resolved_data_dir,
                    timeout_seconds=timeout_seconds,
                )
            )
        except DoctorTimeoutError as exc:
            stdio_checks = _failed_stdio_checks()
            failure = {
                "code": "MCP_TIMEOUT",
                "stage": exc.stage,
                "message": "stdio MCP diagnostic timed out",
            }
            errors.append(f"stdio MCP diagnostic timed out during {exc.stage}")
        except Exception as exc:  # pragma: no cover - platform failures remain in the report
            stdio_checks = _failed_stdio_checks()
            failure = {
                "code": "MCP_CHECK_FAILED",
                "stage": "stdio",
                "message": "stdio MCP diagnostic failed",
            }
            errors.append(f"stdio MCP check failed: {type(exc).__name__}")

    after = _sha256(resolved_database)
    checks = {
        "database_schema": True,
        "release_metadata": bool(release.get("release_id")),
        **stdio_checks,
        "database_unchanged": before == after,
    }
    if resolved_data_dir is not None or target.pointer is not None:
        try:
            final_target = resolve_database(database, data_dir=resolved_data_dir)
        except (OSError, ValueError):
            pointer_unchanged = False
        else:
            pointer_unchanged = final_target == target
        checks["current_pointer_unchanged"] = pointer_unchanged
    if target.pointer is not None:
        checks["database_matches_current_pointer"] = (
            before == target.pointer.database_sha256.upper()
        )
    for name, passed in checks.items():
        if not passed:
            errors.append(f"check failed: {name}")
    if failure is None and not all(stdio_checks.values()):
        failure = {
            "code": "MCP_CONTRACT_FAILED",
            "stage": "tool_validation",
            "message": "one or more stdio MCP contract checks failed",
        }
    return DoctorResult(
        ok=all(checks.values()),
        database=resolved_database,
        database_sha256=after,
        release=release,
        checks=checks,
        tool_names=tool_names,
        sample={"input": sample_input, "output": sample_output},
        errors=tuple(errors),
        failure=failure,
    )
