from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp.client.stdio import StdioServerParameters

import pmgs_reference.diagnostics as diagnostics_module
from pmgs_reference.diagnostics import (
    EXPECTED_MCP_TOOLS,
    DoctorTimeoutError,
    doctor_database,
)

_SAMPLE = {
    "scheme": "fi",
    "code": "G06F3/048",
    "edition": None,
    "version": None,
}


def _pid_is_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_stdio_timeout_cancels_the_check_and_releases_its_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"closed": False}

    @asynccontextmanager
    async def active_check() -> Any:
        try:
            yield
        finally:
            state["closed"] = True

    async def hanging_check(*args: object, **kwargs: object) -> object:
        stage = kwargs["stage"]
        assert isinstance(stage, list)
        stage[0] = "search_pmgs"
        async with active_check():
            await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(diagnostics_module, "_check_stdio", hanging_check)

    with pytest.raises(DoctorTimeoutError) as error:
        asyncio.run(
            diagnostics_module._run_stdio_check(
                Path("synthetic.sqlite"),
                Path(sys.executable),
                _SAMPLE,
                search_query="Synthetic",
                document_id="doc-aaaaaaaaaaaaaaaaaaaaaaaa",
                timeout_seconds=0.01,
            )
        )

    assert error.value.stage == "search_pmgs"
    assert state["closed"] is True


@pytest.mark.parametrize(
    "stage_name",
    ["stdio_start", "initialize", "list_tools", "lookup_classification", "get_pmgs_document"],
)
def test_stdio_timeout_preserves_the_active_stage(
    monkeypatch: pytest.MonkeyPatch, stage_name: str
) -> None:
    async def hanging_check(*args: object, **kwargs: object) -> object:
        stage = kwargs["stage"]
        assert isinstance(stage, list)
        stage[0] = stage_name
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(diagnostics_module, "_check_stdio", hanging_check)

    with pytest.raises(DoctorTimeoutError) as error:
        asyncio.run(
            diagnostics_module._run_stdio_check(
                Path("synthetic.sqlite"),
                Path(sys.executable),
                _SAMPLE,
                search_query="Synthetic",
                document_id="doc-aaaaaaaaaaaaaaaaaaaaaaaa",
                timeout_seconds=0.01,
            )
        )

    assert error.value.stage == stage_name


def test_real_stdio_timeout_terminates_the_child_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    server = Path(__file__).parent / "fixtures" / "hanging_stdio_server.py"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(server)],
        env={**os.environ, "PMGS_TEST_PID_FILE": str(pid_file)},
    )

    with pytest.raises(DoctorTimeoutError) as error:
        asyncio.run(
            diagnostics_module._run_stdio_check(
                Path("synthetic.sqlite"),
                Path(sys.executable),
                _SAMPLE,
                search_query="Synthetic",
                document_id="doc-aaaaaaaaaaaaaaaaaaaaaaaa",
                timeout_seconds=1.0,
                server_parameters=parameters,
            )
        )

    assert error.value.stage == "initialize"
    assert pid_file.is_file()
    pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3.0
    while _pid_is_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _pid_is_running(pid) is False


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("nan"), float("inf")])
def test_doctor_rejects_non_finite_or_non_positive_timeouts(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        diagnostics_module.doctor_database(
            Path("not-opened.sqlite"),
            timeout_seconds=timeout_seconds,
        )


def test_doctor_reports_a_structured_timeout_failure(
    synthetic_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hanging_check(*args: object, **kwargs: object) -> object:
        stage = kwargs["stage"]
        assert isinstance(stage, list)
        stage[0] = "get_pmgs_document"
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
        "stage": "get_pmgs_document",
        "message": "stdio MCP diagnostic timed out",
    }
    assert result.checks["sample_lookup"] is False
    assert result.checks["sample_search"] is False
    assert result.checks["sample_document"] is False


def test_doctor_reports_a_structured_sample_selection_failure(
    synthetic_database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        diagnostics_module,
        "_document_sample",
        lambda _database: (_ for _ in ()).throw(ValueError("private detail")),
    )

    result = doctor_database(synthetic_database, python_executable=sys.executable)

    assert result.ok is False
    assert result.failure == {
        "code": "SAMPLE_SELECTION_FAILED",
        "stage": "sample_selection",
        "message": "unable to select deterministic doctor samples",
    }
    assert "private detail" not in "\n".join(result.errors)


def test_doctor_calls_and_validates_all_three_mcp_tools(synthetic_database: Path) -> None:
    result = doctor_database(
        synthetic_database,
        python_executable=sys.executable,
        timeout_seconds=30.0,
    )

    assert result.ok is True
    assert result.failure is None
    assert result.checks["sample_lookup"] is True
    assert result.checks["sample_search"] is True
    assert result.checks["sample_document"] is True
    assert set(result.sample["output"]) == {"lookup", "search", "document"}


@pytest.mark.parametrize("failed_check", ["sample_search", "sample_document"])
def test_doctor_fails_when_one_tool_contract_is_broken(
    synthetic_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_check: str,
) -> None:
    async def incomplete_check(*args: object, **kwargs: object) -> object:
        checks = {
            "mcp_server_identity": True,
            "mcp_tool_contract": True,
            "mcp_tools_read_only": True,
            "sample_lookup": True,
            "sample_search": True,
            "sample_document": True,
        }
        checks[failed_check] = False
        return checks, EXPECTED_MCP_TOOLS, {"lookup": {}, "search": {}, "document": {}}

    monkeypatch.setattr(diagnostics_module, "_run_stdio_check", incomplete_check)

    result = doctor_database(synthetic_database, python_executable=sys.executable)

    assert result.ok is False
    assert result.checks[failed_check] is False
    assert result.failure == {
        "code": "MCP_CONTRACT_FAILED",
        "stage": "tool_validation",
        "message": "one or more stdio MCP contract checks failed",
    }
