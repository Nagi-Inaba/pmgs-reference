"""Read-only local stdio MCP adapter for PMGS Reference."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, InputRequiredResult, TextContent, ToolAnnotations
from pydantic import Field

from pmgs_reference import __version__
from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.store import JSONValue, PMGSStore

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
Scheme = Literal["fi", "fterm", "ipc"]
Language = Literal["ja", "en"]
ContentType = Literal["classification", "document"]
Code = Annotated[str, Field(min_length=1, max_length=128)]
Query = Annotated[str, Field(min_length=1, max_length=500)]
Release = Annotated[str, Field(min_length=1, max_length=64)]
Edition = Annotated[str, Field(min_length=1, max_length=64)]
Version = Annotated[
    str,
    Field(pattern=r"^(?:[0-9]{4}\.[0-9]{2}|\([0-9]{4}\.[0-9]{2}\))$"),
]
Section = Annotated[str, Field(min_length=1, max_length=128)]
Limit = Annotated[int, Field(ge=1, le=100)]
RelationLimit = Annotated[int, Field(ge=1, le=200)]
Offset = Annotated[int, Field(ge=0)]
Schemes = Annotated[list[Scheme], Field(min_length=1, max_length=3)]
ContentTypes = Annotated[list[ContentType], Field(min_length=1, max_length=2)]


def _tool_error(error: PMGSQueryError) -> ToolError:
    return ToolError(json.dumps(error.as_dict(), ensure_ascii=False, sort_keys=True))


def _database_tool_error() -> ToolError:
    return ToolError(
        json.dumps(
            {
                "code": "DATABASE_ERROR",
                "message": "PMGS Reference database query failed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


class PMGSMCPServer(MCPServer[None]):
    """Expose direct calls with the same isError shape as protocol calls."""

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
    ) -> CallToolResult | InputRequiredResult:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as error:
            return CallToolResult(
                content=[TextContent(type="text", text=str(error))],
                is_error=True,
            )


def create_server(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> MCPServer[None]:
    """Create the three-tool PMGS stdio server for an already-built database."""
    store = PMGSStore.open(database, data_dir=data_dir)
    server: MCPServer[None] = PMGSMCPServer(
        name="pmgs-reference",
        title="PMGS Reference",
        description="Exact, versioned reference access to registered PMGS data",
        version=__version__,
        log_level="ERROR",
    )

    @server.tool(
        name="lookup_classification",
        description=(
            "Look up one exact FI, F-term, or IPC classification definition. "
            "No AI summary or inferred classification is returned."
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def lookup_classification(
        scheme: Scheme,
        code: Code,
        release: Release = "current",
        edition: Edition | None = None,
        version: Version | None = None,
        language: Language = "ja",
        relation_limit: RelationLimit = 50,
        relation_offset: Offset = 0,
    ) -> dict[str, JSONValue]:
        try:
            return store.lookup(
                scheme,
                code,
                release,
                edition,
                language,
                version=version,
                relation_limit=relation_limit,
                relation_offset=relation_offset,
            )
        except PMGSQueryError as error:
            raise _tool_error(error) from error
        except (OSError, sqlite3.Error, ValueError) as error:
            raise _database_tool_error() from error

    @server.tool(
        name="search_pmgs",
        description=(
            "Run bounded SQLite FTS5 lexical search over JPO-provided classification and/or "
            "document text. This is not semantic search."
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def search_pmgs(
        query: Query,
        schemes: Schemes | None = None,
        content_types: ContentTypes | None = None,
        release: Release = "current",
        language: Language = "ja",
        limit: Limit = 20,
    ) -> dict[str, JSONValue]:
        try:
            return store.search_pmgs(query, schemes, content_types, release, language, limit)
        except PMGSQueryError as error:
            raise _tool_error(error) from error
        except (OSError, sqlite3.Error, ValueError) as error:
            raise _database_tool_error() from error

    @server.tool(
        name="get_pmgs_document",
        description="Get bounded JPO-provided PMGS document text by stable document identifier.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def get_pmgs_document(
        document_id: Code,
        page: Annotated[int, Field(ge=1)] | None = None,
        section: Section | None = None,
    ) -> dict[str, JSONValue]:
        try:
            return store.get_document(document_id, page, section)
        except PMGSQueryError as error:
            raise _tool_error(error) from error
        except (OSError, sqlite3.Error, ValueError) as error:
            raise _database_tool_error() from error

    return server


def run_stdio(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> None:
    """Run the PMGS MCP server over stdin/stdout only."""
    create_server(database, data_dir=data_dir).run(transport="stdio")
