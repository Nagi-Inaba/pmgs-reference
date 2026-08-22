from __future__ import annotations

from pathlib import Path

import pytest

import pmgs_reference.data_paths as data_paths_module
import pmgs_reference.setup as setup_impl
from pmgs_reference.data_paths import write_json_atomic
from pmgs_reference.setup import SetupResult, setup_reference


def test_atomic_json_replace_syncs_the_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    real_sync = data_paths_module.fsync_directory

    def recording_sync(path: Path) -> None:
        calls.append(path)
        real_sync(path)

    monkeypatch.setattr(data_paths_module, "fsync_directory", recording_sync)
    destination = tmp_path / "state" / "current.json"

    write_json_atomic(destination, {"status": "ready"})

    assert calls == [destination.parent]
    assert destination.read_text(encoding="utf-8").endswith("\n")


def test_setup_result_exposes_post_activation_phase_state() -> None:
    fields = SetupResult.__dataclass_fields__

    assert {
        "database_ready",
        "pointer_changed",
        "client_integration_started",
        "report_write_failed",
    } <= fields.keys()


def test_post_activation_client_exception_is_reported_as_partial_success(
    synthetic_pmgs: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def crash_after_activation(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated client phase failure")

    monkeypatch.setattr(setup_impl, "integrate_clients", crash_after_activation)
    data_root = tmp_path / "pmgs-reference"

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=(),
        approved_clients=(),
    )

    assert result.status == "partial_failed"
    assert result.database_ready is True
    assert result.pointer_changed is True
    assert result.client_integration_started is True
    assert result.database is not None
    assert result.current_pointer is not None
    assert result.restart_required is True
    assert result.report_write_failed is False


def test_directory_sync_failure_does_not_report_success(
    synthetic_pmgs: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_directory_sync(path: Path) -> None:
        raise OSError("simulated directory sync failure")

    monkeypatch.setattr(data_paths_module, "fsync_directory", fail_directory_sync)

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=tmp_path / "pmgs-reference",
        client_targets=(),
        approved_clients=(),
    )

    assert result.status == "failed"
    assert result.pointer_changed is False
    assert result.current_pointer is None
