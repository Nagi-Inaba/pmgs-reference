from __future__ import annotations

from pathlib import Path

import pytest

import pmgs_reference.setup as setup_service
from pmgs_reference.diagnostics import DoctorResult
from pmgs_reference.setup import setup_reference


def _timeout_result(database: Path) -> DoctorResult:
    return DoctorResult(
        ok=False,
        database=database,
        database_sha256="0" * 64,
        release={"release_id": "JPPM2099001"},
        checks={
            "database_schema": True,
            "release_metadata": True,
            "mcp_server_identity": False,
            "mcp_tool_contract": False,
            "mcp_tools_read_only": False,
            "sample_lookup": False,
            "sample_search": False,
            "sample_document": False,
            "database_unchanged": True,
        },
        tool_names=(),
        sample={"input": {}, "output": {}},
        errors=("stdio MCP diagnostic timed out during initialize",),
        failure={
            "code": "MCP_TIMEOUT",
            "stage": "initialize",
            "message": "stdio MCP diagnostic timed out",
        },
    )


def test_setup_lock_is_released_after_a_doctor_timeout(
    synthetic_pmgs: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "pmgs-reference"
    real_doctor = setup_service.doctor_database
    calls = 0

    def fail_once(database: str | Path, **kwargs: object) -> DoctorResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _timeout_result(Path(database))
        return real_doctor(database, **kwargs)

    monkeypatch.setattr(setup_service, "doctor_database", fail_once)

    failed = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=(),
        approved_clients=(),
    )
    retried = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=(),
        approved_clients=(),
    )

    assert failed.status == "failed"
    assert any("stdio MCP diagnostic" in error for error in failed.errors)
    assert retried.status == "ready"
    assert calls == 2
    assert not any("already running" in error for error in retried.errors)
