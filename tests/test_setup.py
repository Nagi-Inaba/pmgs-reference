from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import pmgs_reference.setup as local_setup_module
from pmgs_reference.client_integration import ClientTarget
from pmgs_reference.data_paths import write_json_atomic
from pmgs_reference.ingest.build import BuildError, build_database
from pmgs_reference.ingest.inventory import build_inventory
from pmgs_reference.schema import APPLICATION_ID
from pmgs_reference.setup import SetupLock, SetupUsageError, resolve_setup_source, setup_reference
from pmgs_reference.store import PMGSStore
from pmgs_reference.validation import validate_database


def _no_clients() -> tuple[ClientTarget, ...]:
    return ()


def _create_v1_database(path: Path, release_id: str, source_sha256: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            PRAGMA application_id = {APPLICATION_ID};
            PRAGMA user_version = 1;
            CREATE TABLE release (
                release_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                source_manifest_sha256 TEXT NOT NULL,
                source_file_count INTEGER NOT NULL,
                source_total_bytes INTEGER NOT NULL
            ) STRICT;
            """
        )
        connection.execute(
            "INSERT INTO release VALUES (?, '1.0', ?, 1, 1)",
            (release_id, source_sha256),
        )
        connection.commit()
    finally:
        connection.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    destination = path.with_name(f"{digest}.sqlite")
    path.rename(destination)
    return digest


def test_resolve_setup_source_uses_the_package_name_or_one_direct_child(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    named = tmp_path / "named" / "JPPM2099001"
    shutil.copytree(synthetic_pmgs, named)
    source, release, origin = resolve_setup_source(named, None)
    assert (source, release, origin) == (named.resolve(), "JPPM2099001", "directory_name")

    parent = tmp_path / "downloads"
    parent.mkdir()
    child = parent / "JPPM2099002"
    shutil.copytree(synthetic_pmgs, child)
    source, release, origin = resolve_setup_source(parent, None)
    assert (source, release, origin) == (child.resolve(), "JPPM2099002", "single_child")


def test_resolve_setup_source_rejects_ambiguous_and_mismatched_releases(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    parent = tmp_path / "downloads"
    parent.mkdir()
    shutil.copytree(synthetic_pmgs, parent / "JPPM2099001")
    shutil.copytree(synthetic_pmgs, parent / "JPPM2099002")

    with pytest.raises(SetupUsageError, match="multiple"):
        resolve_setup_source(parent, None)
    with pytest.raises(SetupUsageError, match="does not match"):
        resolve_setup_source(parent / "JPPM2099001", "JPPM2099002")


def test_resolve_setup_source_rejects_an_unextracted_archive(tmp_path: Path) -> None:
    archive = tmp_path / "JPPM2099001.zip"
    archive.write_bytes(b"synthetic archive placeholder")

    with pytest.raises(SetupUsageError, match=r"extract.*archive"):
        resolve_setup_source(archive, None)


def test_setup_builds_activates_and_reuses_an_immutable_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert first.status == "ready"
    assert first.database is not None
    database = Path(first.database)
    assert database.is_file()
    assert database.relative_to(data_root).parts[:2] == ("data", "releases")
    assert PMGSStore.open(data_dir=data_root).release_info()["release_id"] == "JPPM2099001"
    pointer = json.loads((data_root / "state" / "current.json").read_text(encoding="utf-8"))
    assert pointer["database_relpath"] == database.relative_to(data_root).as_posix()
    before_mtime = database.stat().st_mtime_ns

    second = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert second.status == "already_ready"
    assert second.database == first.database
    assert database.stat().st_mtime_ns == before_mtime


def test_setup_promotion_does_not_overwrite_a_racing_destination(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "pmgs-reference"
    existing_bytes = b"concurrent writer"
    real_promote = local_setup_module.promote_database_exclusive
    race_injected = False

    def racing_promote(source: Path, destination: Path, *, permission_attempts: int = 1) -> None:
        nonlocal race_injected
        race_injected = True
        destination.write_bytes(existing_bytes)
        real_promote(source, destination, permission_attempts=permission_attempts)

    monkeypatch.setattr(local_setup_module, "promote_database_exclusive", racing_promote)
    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert race_injected is True
    assert result.status == "failed"
    assert any("database output already exists" in error for error in result.errors)
    destinations = list((data_root / "data" / "releases").rglob("*.sqlite"))
    assert len(destinations) == 1
    assert destinations[0].read_bytes() == existing_bytes
    assert not (data_root / "state" / "current.json").exists()


def test_setup_reuses_the_locked_current_validation(
    synthetic_pmgs: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert first.status == "ready"
    real_validate = local_setup_module.validate_database
    calls = 0

    def counting_validate(path: Path) -> object:
        nonlocal calls
        calls += 1
        return real_validate(path)

    monkeypatch.setattr(local_setup_module, "validate_database", counting_validate)

    second = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert second.status == "already_ready"
    assert calls == 1


def test_setup_rejects_a_current_database_whose_bytes_changed(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert first.database is not None
    pointer_path = data_root / "state" / "current.json"
    pointer_before = pointer_path.read_bytes()
    connection = sqlite3.connect(first.database)
    try:
        connection.execute(
            "UPDATE concept_text SET text = text || ' tampered' "
            "WHERE rowid = (SELECT rowid FROM concept_text LIMIT 1)"
        )
        connection.commit()
    finally:
        connection.close()

    second = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert second.status == "failed"
    assert any("current.json metadata does not match" in error for error in second.errors)
    assert pointer_path.read_bytes() == pointer_before


def test_setup_dry_run_performs_inventory_without_writing(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.inventory["file_count"] == 26
    assert result.storage["planned_build"] is True
    assert result.storage["required_free_bytes"] == (
        int(result.inventory["total_bytes"]) * 7 + 512 * 1024 * 1024
    )
    assert not data_root.exists()


def test_setup_fails_before_build_when_disk_capacity_is_insufficient(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "pmgs-reference"
    build_called = False

    def insufficient(_path: Path) -> object:
        return SimpleNamespace(free=1)

    def unexpected_build(*_args: object, **_kwargs: object) -> object:
        nonlocal build_called
        build_called = True
        raise AssertionError("build must not start without sufficient capacity")

    monkeypatch.setattr(local_setup_module.shutil, "disk_usage", insufficient)
    monkeypatch.setattr(local_setup_module, "build_database", unexpected_build)

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "failed"
    assert result.storage["planned_build"] is True
    assert result.storage["sufficient"] is False
    assert build_called is False
    assert not list(data_root.rglob("candidate.sqlite"))


def test_setup_rebuilds_v1_without_changing_it_until_v2_activation(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    inventory = build_inventory(synthetic_pmgs)
    provisional = (
        data_root / "data" / "releases" / "JPPM2099001" / inventory.logical_sha256 / "v1.sqlite"
    )
    v1_sha256 = _create_v1_database(provisional, "JPPM2099001", inventory.logical_sha256)
    v1_database = provisional.with_name(f"{v1_sha256}.sqlite")
    v1_bytes = v1_database.read_bytes()
    pointer_path = data_root / "state" / "current.json"
    write_json_atomic(
        pointer_path,
        {
            "schema_version": "1.0",
            "release_id": "JPPM2099001",
            "source_manifest_sha256": inventory.logical_sha256,
            "database_sha256": v1_sha256,
            "database_schema_version": 1,
            "database_relpath": v1_database.relative_to(data_root).as_posix(),
            "activated_at": "2099-01-01T00:00:00Z",
        },
    )

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "ready"
    assert result.database_schema_version == 2
    assert result.database is not None and Path(result.database) != v1_database
    assert v1_database.read_bytes() == v1_bytes
    current = json.loads(pointer_path.read_text(encoding="utf-8"))
    assert current["database_schema_version"] == 2
    assert result.storage["retained_database_count"] >= 1  # type: ignore[operator]


def test_setup_dry_run_reports_approved_clients_as_planned(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=tmp_path / "pmgs-reference",
        client_targets=(ClientTarget("codex", tmp_path / "codex.exe"),),
        approved_clients=("codex",),
        dry_run=True,
    )

    assert result.clients[0]["status"] == "planned_registration"
    assert result.clients[0]["error"] is None


def test_setup_lock_is_non_waiting(tmp_path: Path) -> None:
    data_root = tmp_path / "pmgs-reference"
    data_root.mkdir()

    with (
        SetupLock(data_root / "setup.lock", "first"),
        pytest.raises(OSError, match="already running"),
        SetupLock(data_root / "setup.lock", "second"),
    ):
        pass

    with SetupLock(data_root / "setup.lock", "third"):
        pass


def test_setup_lock_excludes_another_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "pmgs-reference" / "setup.lock"
    probe = (
        "import sys\n"
        "from pathlib import Path\n"
        "from pmgs_reference.setup import SetupLock\n"
        "try:\n"
        "    with SetupLock(Path(sys.argv[1]), 'child'):\n"
        "        pass\n"
        "except OSError:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )

    with SetupLock(lock_path, "parent"):
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(lock_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )

    assert completed.returncode == 0, completed.stderr


def test_setup_reloads_current_pointer_after_acquiring_the_lock(
    synthetic_pmgs: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "pmgs-reference"
    inventory = build_inventory(synthetic_pmgs)
    prebuilt = tmp_path / "prebuilt.sqlite"
    build_database(synthetic_pmgs, "JPPM2099001", prebuilt)
    validation = validate_database(prebuilt)
    database = (
        data_root
        / "data"
        / "releases"
        / "JPPM2099001"
        / inventory.logical_sha256
        / f"{validation.database_sha256}.sqlite"
    )
    database.parent.mkdir(parents=True)
    shutil.copy2(prebuilt, database)
    pointer_payload = {
        "schema_version": "1.0",
        "release_id": "JPPM2099001",
        "source_manifest_sha256": inventory.logical_sha256,
        "database_sha256": validation.database_sha256,
        "database_schema_version": validation.user_version,
        "database_relpath": database.relative_to(data_root).as_posix(),
        "activated_at": "2099-01-01T00:00:00Z",
    }
    original_enter = SetupLock.__enter__

    def publish_pointer_after_lock(lock: SetupLock) -> SetupLock:
        result = original_enter(lock)
        write_json_atomic(data_root / "state" / "current.json", pointer_payload)
        return result

    monkeypatch.setattr(SetupLock, "__enter__", publish_pointer_after_lock)

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "already_ready"
    assert (
        json.loads((data_root / "state" / "current.json").read_text(encoding="utf-8"))
        == pointer_payload
    )


def test_setup_migrates_a_matching_legacy_current_database(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    legacy = data_root / "data" / "current.sqlite"
    legacy.parent.mkdir(parents=True)
    build_database(synthetic_pmgs, "JPPM2099001", legacy)
    before = legacy.read_bytes()

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    pointer = json.loads((data_root / "state" / "current.json").read_text(encoding="utf-8"))
    assert result.status == "already_ready"
    assert pointer["database_relpath"] == "data/current.sqlite"
    assert legacy.read_bytes() == before


def test_setup_retains_a_corrupt_legacy_database_and_rebuilds(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    legacy = data_root / "data" / "current.sqlite"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"not a sqlite database")

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "ready"
    assert legacy.read_bytes() == b"not a sqlite database"
    assert result.database != str(legacy)
    assert "legacy current.sqlite is invalid and was retained" in result.warnings


def test_setup_retains_a_corrupt_versioned_database_and_rebuilds(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    source_sha256 = build_inventory(synthetic_pmgs).logical_sha256
    corrupt = data_root / "data" / "releases" / "JPPM2099001" / source_sha256 / f"{'A' * 64}.sqlite"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"not a sqlite database")

    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "ready"
    assert corrupt.read_bytes() == b"not a sqlite database"
    assert result.database != str(corrupt)
    assert f"invalid database retained: {corrupt.name}" in result.warnings


def test_setup_rejects_a_link_inside_the_managed_data_root(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    outside = tmp_path / "outside"
    data_root.mkdir()
    outside.mkdir()
    try:
        (data_root / "state").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(SetupUsageError, match="link or reparse point"):
        setup_reference(
            synthetic_pmgs,
            release_id="JPPM2099001",
            data_dir=data_root,
            client_targets=_no_clients(),
            approved_clients=(),
            dry_run=True,
        )

    assert list(outside.iterdir()) == []


def test_setup_does_not_activate_when_build_reports_source_changed(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "pmgs-reference"
    current = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert current.status == "ready"
    assert current.database is not None
    pointer_path = data_root / "state" / "current.json"
    pointer_before = pointer_path.read_bytes()
    source = tmp_path / "mutable" / "JPPM2099001"
    shutil.copytree(synthetic_pmgs, source)
    copyright_file = source / "COPYRGHT"
    copyright_file.write_text(
        copyright_file.read_text(encoding="utf-8") + "variant\n", encoding="utf-8"
    )

    def changed_source_build(*args: object, **kwargs: object) -> object:
        raise BuildError("source changed while the database was being built")

    monkeypatch.setattr(local_setup_module, "build_database", changed_source_build)

    result = setup_reference(
        source,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert result.status == "failed"
    assert any("changed" in error for error in result.errors)
    assert pointer_path.read_bytes() == pointer_before
    assert PMGSStore.open(data_dir=data_root).path == Path(current.database)
    assert list((data_root / "data" / "releases").rglob("*.sqlite")) == [Path(current.database)]
    assert build_inventory(source).logical_sha256 == result.source_manifest_sha256


def test_client_failure_returns_partial_failed_but_keeps_the_database_ready(
    synthetic_pmgs: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_client(*args: object, **kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "client": "codex",
                "status": "failed",
                "mcp": "failed",
                "skill": "not_checked",
                "restart_required": False,
                "error": "simulated failure",
            }
        ]

    monkeypatch.setattr(local_setup_module, "integrate_clients", failed_client)
    data_root = tmp_path / "pmgs-reference"
    result = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=(ClientTarget("codex", tmp_path / "codex.exe"),),
        approved_clients=("codex",),
    )

    assert result.status == "partial_failed"
    assert result.database is not None
    assert PMGSStore.open(data_dir=data_root).release_info()["release_id"] == "JPPM2099001"
    assert (data_root / "state" / "current.json").is_file()


def test_pointer_switch_requires_restart_for_a_detected_declined_client(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert first.status == "ready"

    updated_source = tmp_path / "updated" / "JPPM2099002"
    shutil.copytree(synthetic_pmgs, updated_source)

    second = setup_reference(
        updated_source,
        release_id="JPPM2099002",
        data_dir=data_root,
        client_targets=(ClientTarget("codex", tmp_path / "codex.exe"),),
        approved_clients=(),
    )

    assert second.status == "ready"
    assert second.clients[0]["status"] == "declined"
    assert second.restart_required is True


def test_reactivating_a_reused_database_reports_ready(synthetic_pmgs: Path, tmp_path: Path) -> None:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert first.status == "ready"

    updated_source = tmp_path / "updated" / "JPPM2099002"
    shutil.copytree(synthetic_pmgs, updated_source)
    second = setup_reference(
        updated_source,
        release_id="JPPM2099002",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )
    assert second.status == "ready"

    reactivated = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=_no_clients(),
        approved_clients=(),
    )

    assert reactivated.database_reused is True
    assert reactivated.status == "ready"
    assert PMGSStore.open(data_dir=data_root).release_info()["release_id"] == "JPPM2099001"
