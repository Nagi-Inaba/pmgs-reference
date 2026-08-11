from __future__ import annotations

import json
from pathlib import Path

import pytest

import pmgs_reference.data_paths as data_paths_module
from pmgs_reference.data_paths import (
    CurrentPointerError,
    default_data_root,
    read_current_pointer,
    write_json_atomic,
)


def test_default_data_roots_cover_windows_macos_and_linux(tmp_path: Path) -> None:
    windows = default_data_root(
        platform="win32",
        environ={"LOCALAPPDATA": str(tmp_path / "Local")},
        home=tmp_path / "home",
    )
    macos = default_data_root(platform="darwin", environ={}, home=tmp_path / "home")
    linux = default_data_root(
        platform="linux",
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path / "home",
    )
    linux_fallback = default_data_root(platform="linux", environ={}, home=tmp_path / "home")

    assert windows == (tmp_path / "Local" / "pmgs-reference").absolute()
    assert (
        macos
        == (tmp_path / "home" / "Library" / "Application Support" / "pmgs-reference").absolute()
    )
    assert linux == (tmp_path / "xdg" / "pmgs-reference").absolute()
    assert linux_fallback == (tmp_path / "home" / ".local" / "share" / "pmgs-reference").absolute()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("release_id", "release-latest"),
        ("source_manifest_sha256", "not-a-sha"),
        ("database_sha256", "0" * 63),
    ],
)
def test_current_pointer_rejects_invalid_identity_fields(
    tmp_path: Path, field: str, invalid: str
) -> None:
    database = tmp_path / "data" / "releases" / "JPPM2099001" / "database.sqlite"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"synthetic")
    state = tmp_path / "state"
    state.mkdir()
    payload = {
        "schema_version": "1.0",
        "release_id": "JPPM2099001",
        "source_manifest_sha256": "A" * 64,
        "database_sha256": "B" * 64,
        "database_schema_version": 1,
        "database_relpath": database.relative_to(tmp_path).as_posix(),
        "activated_at": "2099-01-01T00:00:00Z",
    }
    payload[field] = invalid
    (state / "current.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CurrentPointerError, match=field):
        read_current_pointer(tmp_path)


def test_atomic_json_failure_preserves_the_previous_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "state" / "current.json"
    write_json_atomic(pointer, {"schema_version": "old", "value": 1})
    before = pointer.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(data_paths_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        write_json_atomic(pointer, {"schema_version": "new", "value": 2})

    assert pointer.read_bytes() == before
    assert list(pointer.parent.glob(".current.json-*.tmp")) == []
