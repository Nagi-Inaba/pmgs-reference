from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmgs_reference.publication.output_management import (
    cleanup_public_output,
    inspect_public_output,
    write_public_output_marker,
)


def _owned_failed_tree(root: Path) -> None:
    root.mkdir()
    write_public_output_marker(
        root,
        {
            "schema_version": "1.0",
            "run_id": "run-aaaaaaaaaaaaaaaa",
            "database_sha256": "A" * 64,
            "source_manifest_sha256": "B" * 64,
            "publication_policy_sha256": "C" * 64,
            "base_url": "https://pmgs.example.test",
            "started_at": "2099-01-01T00:00:00Z",
            "status": "failed",
        },
    )
    (root / "partial.json").write_text('{"partial":true}\n', encoding="utf-8")


def test_inspect_and_dry_run_identify_owned_failed_tree(tmp_path: Path) -> None:
    root = tmp_path / "failed-public-output"
    _owned_failed_tree(root)

    inspected = inspect_public_output(root)
    plan = cleanup_public_output(root, dry_run=True)

    assert inspected["owned"] is True
    assert inspected["status"] == "failed"
    assert inspected["complete"] is False
    assert inspected["bytes"] > 0
    assert plan["status"] == "planned"
    assert plan["root"] == str(root)
    assert plan["reclaim_bytes"] == inspected["bytes"]
    assert root.is_dir()


def test_cleanup_refuses_unowned_and_completed_directories(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "important.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="owned"):
        cleanup_public_output(foreign, dry_run=False)
    assert (foreign / "important.txt").is_file()

    complete = tmp_path / "complete"
    _owned_failed_tree(complete)
    marker = complete / ".pmgs-public-output.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["status"] = "complete"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    (complete / "releases").mkdir()
    (complete / "releases" / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="complete"):
        cleanup_public_output(complete, dry_run=False)
    assert complete.is_dir()


def test_cleanup_rejects_links_and_only_removes_verified_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "protected.txt"
    protected.write_text("keep", encoding="utf-8")

    linked = tmp_path / "linked"
    _owned_failed_tree(linked)
    try:
        (linked / "escape").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="link"):
        cleanup_public_output(linked, dry_run=False)
    assert protected.read_text(encoding="utf-8") == "keep"

    safe = tmp_path / "safe"
    _owned_failed_tree(safe)
    result = cleanup_public_output(safe, dry_run=False)

    assert result["status"] == "removed"
    assert not safe.exists()
    assert protected.read_text(encoding="utf-8") == "keep"
