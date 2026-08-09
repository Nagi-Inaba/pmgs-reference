from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmgs_reference.cli import main


def test_inventory_command_writes_default_summary(
    synthetic_pmgs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "source-manifest.jsonl"
    result = main(["inventory", str(synthetic_pmgs), "--output", str(manifest)])

    assert result == 0
    assert manifest.exists()
    summary_path = tmp_path / "inventory-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["file_count"] == 26
    assert summary["status_counts"] == {"parsed": 24, "retained": 2}

    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    assert printed["logical_sha256"] == summary["logical_sha256"]
