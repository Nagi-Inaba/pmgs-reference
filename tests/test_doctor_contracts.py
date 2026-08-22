from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import pmgs_reference.diagnostics as diagnostics_module
from pmgs_reference.diagnostics import doctor_database


def test_doctor_exercises_lookup_search_and_document_over_stdio(
    synthetic_database: Path,
) -> None:
    result = doctor_database(
        synthetic_database,
        python_executable=sys.executable,
        timeout_seconds=30,
    )

    assert result.ok is True
    assert result.checks["sample_lookup"] is True
    assert result.checks["sample_search"] is True
    assert result.checks["sample_document"] is True
    assert set(result.sample["output"]) == {"lookup", "search", "document"}


def test_doctor_returns_a_bounded_timeout_error(
    synthetic_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stalled_check(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    monkeypatch.setattr(diagnostics_module, "_check_stdio", stalled_check)

    result = doctor_database(
        synthetic_database,
        python_executable=sys.executable,
        timeout_seconds=0.01,
    )

    assert result.ok is False
    assert "MCP_TIMEOUT:diagnostic" in result.errors
    assert result.checks["sample_lookup"] is False
    assert result.checks["sample_search"] is False
    assert result.checks["sample_document"] is False
    assert result.checks["database_unchanged"] is True


def test_doctor_rejects_non_positive_timeout(synthetic_database: Path) -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        doctor_database(synthetic_database, timeout_seconds=0)
