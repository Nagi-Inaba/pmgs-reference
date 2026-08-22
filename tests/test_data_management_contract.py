from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pmgs_reference.cli import main
from pmgs_reference.data_management import activate_database, list_databases, prune_databases
from pmgs_reference.setup import setup_reference


def _build_two_releases(synthetic_pmgs: Path, tmp_path: Path) -> Path:
    data_root = tmp_path / "pmgs-reference"
    first = setup_reference(
        synthetic_pmgs,
        release_id="JPPM2099001",
        data_dir=data_root,
        client_targets=(),
        approved_clients=(),
    )
    assert first.database is not None

    second_source = tmp_path / "JPPM2099002"
    shutil.copytree(synthetic_pmgs, second_source)
    second = setup_reference(
        second_source,
        release_id="JPPM2099002",
        data_dir=data_root,
        client_targets=(),
        approved_clients=(),
    )
    assert second.database is not None
    return data_root


def test_list_and_use_validate_identity_before_switching(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = _build_two_releases(synthetic_pmgs, tmp_path)
    listing = list_databases(data_root)

    assert len(listing["databases"]) == 2
    current = next(item for item in listing["databases"] if item["current"])
    previous = next(item for item in listing["databases"] if not item["current"])
    assert current["release_id"] == "JPPM2099002"
    assert previous["release_id"] == "JPPM2099001"
    assert all(item["validation_status"] == "valid" for item in listing["databases"])

    dry_run = activate_database(data_root, previous["database_id"], dry_run=True)
    assert dry_run["status"] == "planned"
    assert list_databases(data_root)["current_database_id"] == current["database_id"]

    activated = activate_database(data_root, previous["database_id"], dry_run=False)
    assert activated["status"] == "ready"
    assert list_databases(data_root)["current_database_id"] == previous["database_id"]


def test_prune_never_deletes_current_or_invalid_identity(
    synthetic_pmgs: Path, tmp_path: Path
) -> None:
    data_root = _build_two_releases(synthetic_pmgs, tmp_path)
    listing = list_databases(data_root)
    current = next(item for item in listing["databases"] if item["current"])
    previous = next(item for item in listing["databases"] if not item["current"])

    plan = prune_databases(data_root, keep=1, dry_run=True)
    assert plan["status"] == "planned"
    assert current["database_id"] not in plan["database_ids"]
    assert previous["database_id"] in plan["database_ids"]
    assert Path(previous["path"]).is_file()

    Path(previous["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="identity"):
        prune_databases(data_root, keep=1, dry_run=False)
    assert Path(current["path"]).is_file()


def test_data_cli_returns_machine_readable_list_use_and_prune(
    synthetic_pmgs: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = _build_two_releases(synthetic_pmgs, tmp_path)

    assert main(["data", "list", "--data-dir", str(data_root), "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    previous = next(item for item in listing["databases"] if not item["current"])

    assert (
        main(
            [
                "data",
                "use",
                previous["database_id"],
                "--data-dir",
                str(data_root),
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "planned"

    assert (
        main(
            [
                "data",
                "prune",
                "--data-dir",
                str(data_root),
                "--keep",
                "1",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["current_protected"] is True
