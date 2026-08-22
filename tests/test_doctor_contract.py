from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

import pmgs_reference.diagnostics as diagnostics_module
from pmgs_reference.diagnostics import doctor_database


def test_stdio_timeout_cancels_the_check_and_releases_its_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"closed": False}

    @asynccontextmanager
    async def active_check() -> object:
        try:
            yield
        finally:
            state["closed"] = True

    async def hanging_check(*args: object, **kwargs: object) -> object:
        async with active_check():
            await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(diagnostics_module, "_check_stdio", hanging_check)

    with pytest.raises(TimeoutError):
        asyncio.run(
            diagnostics_module._run_stdio_check(
                Path("synthetic.sqlite"),
                Path(sys.executable),
                {
                    "scheme": "fi",
                    "code": "G06F3/048",
                    "edition": None,
                    "version": None,
                },
                search_query="Synthetic",
                document_id="doc-aaaaaaaaaaaaaaaaaaaaaaaa",
                timeout_seconds=0.01,
            )
        )

    assert state["closed"] is True


def test_doctor_reports_a_structured_timeout_failure(
    synthetic_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hanging_check(*args: object, **kwargs: object) -> object:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(diagnostics_module, "_check_stdio", hanging_check)

    result = doctor_database(
        synthetic_database,
        python_executable=sys.executable,
        timeout_seconds=0.01,
    )

    assert result.ok is False
    assert result.failure == {
        "code": "MCP_TIMEOUT",
        "stage": "stdio",
        "message": "stdio MCP diagnostic timed out",
    }
    assert result.checks["sample_lookup"] is False
    assert result.checks["sample_search"] is False
    assert result.checks["sample_document"] is False


def test_doctor_calls_and_validates_all_three_mcp_tools(synthetic_database: Path) -> None:
    result = doctor_database(
        synthetic_database,
        python_executable=sys.executable,
        timeout_seconds=30.0,
    )

    assert result.ok is True
    assert result.checks["sample_lookup"] is True
    assert result.checks["sample_search"] is True
    assert result.checks["sample_document"] is True
    assert set(result.sample["output"]) == {"lookup", "search", "document"}
