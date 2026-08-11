"""Read-only local stdio MCP adapter for PMGS Reference."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from pmgs_reference import __version__
from pmgs_reference.errors import PMGSQueryError
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_CONTENT_TYPES = frozenset({"classification", "document"})


def _error_payload(error: PMGSQueryError) -> JSONDict:
    return {"error": {"code": error.code, "message": error.message}}


def create_server(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> MCPServer[None]:
    """Create the three-tool PMGS stdio server for an already-built database."""
    store = PMGSStore.open(database, data_dir=data_dir)
    server: MCPServer[None] = MCPServer(
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
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
        language: str = "ja",
    ) -> dict[str, JSONValue]:
        try:
            return store.lookup(scheme, code, release, edition, language)
        except PMGSQueryError as error:
            return _error_payload(error)

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
        query: str,
        schemes: list[str] | None = None,
        content_types: list[str] | None = None,
        release: str = "current",
        language: str = "ja",
        limit: int = 20,
    ) -> dict[str, JSONValue]:
        requested_types = content_types or ["classification", "document"]
        invalid_types = sorted(set(requested_types) - _CONTENT_TYPES)
        if invalid_types or not requested_types:
            return _error_payload(
                PMGSQueryError(
                    "INVALID_CONTENT_TYPE",
                    "content_types must contain classification and/or document",
                )
            )
        try:
            payloads: list[JSONDict] = []
            if "classification" in requested_types:
                payloads.append(store.search(query, schemes, release, language, limit))
            if "document" in requested_types:
                payloads.append(store.search_documents(query, release, language, limit))
        except PMGSQueryError as error:
            return _error_payload(error)
        results: list[JSONValue] = []
        for payload in payloads:
            payload_results = payload.get("results")
            if isinstance(payload_results, list):
                results.extend(payload_results)
        results = results[:limit]
        release_id = str(payloads[0]["release_id"])
        search_modes = sorted({str(payload["search_mode"]) for payload in payloads})
        return {
            "schema_version": "1.0",
            "release_id": release_id,
            "query": query,
            "search_mode": search_modes[0] if len(search_modes) == 1 else "mixed_lexical",
            "content_types": [item for item in requested_types],
            "count": len(results),
            "results": results,
        }

    @server.tool(
        name="get_pmgs_document",
        description="Get bounded JPO-provided PMGS document text by stable document identifier.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def get_pmgs_document(
        document_id: str,
        page: int | None = None,
        section: str | None = None,
    ) -> dict[str, JSONValue]:
        try:
            return store.get_document(document_id, page, section)
        except PMGSQueryError as error:
            return _error_payload(error)

    return server


def run_stdio(
    database: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> None:
    """Run the PMGS MCP server over stdin/stdout only."""
    create_server(database, data_dir=data_dir).run(transport="stdio")
