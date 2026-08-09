from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver import MCPServer

from pmgs_reference.mcp_server import create_server


@pytest.mark.anyio
async def test_mcp_lists_only_three_read_only_tools(synthetic_database: Path) -> None:
    server = create_server(synthetic_database)
    tools = await server.list_tools()

    assert isinstance(server, MCPServer)
    assert [tool.name for tool in tools] == [
        "lookup_classification",
        "search_pmgs",
        "get_pmgs_document",
    ]
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.output_schema is not None


@pytest.mark.anyio
async def test_mcp_tools_return_structured_success_and_errors(synthetic_database: Path) -> None:
    server = create_server(synthetic_database)

    lookup = await server.call_tool("lookup_classification", {"scheme": "fi", "code": "G06F3/048"})
    assert lookup.structured_content is not None
    assert lookup.structured_content["normalized_code"] == "G06F3/048"

    search = await server.call_tool(
        "search_pmgs",
        {
            "query": "Synthetic",
            "schemes": ["fi"],
            "content_types": ["classification"],
            "limit": 3,
        },
    )
    assert search.structured_content is not None
    assert search.structured_content["count"] >= 1

    invalid = await server.call_tool(
        "lookup_classification", {"scheme": "cpc", "code": "G06F3/048"}
    )
    assert invalid.structured_content is not None
    assert invalid.structured_content["error"]["code"] == "INVALID_SCHEME"


@pytest.mark.anyio
async def test_mcp_stdio_protocol_smoke(synthetic_database: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "pmgs_reference.cli",
            "mcp",
            "--db",
            str(synthetic_database),
        ],
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        result = await session.call_tool(
            "lookup_classification", {"scheme": "fterm", "code": "4C083 AA01"}
        )

    assert initialized.server_info.name == "pmgs-reference"
    assert len(listed.tools) == 3
    assert result.structured_content is not None
    assert result.structured_content["normalized_code"] == "4C083AA01"
