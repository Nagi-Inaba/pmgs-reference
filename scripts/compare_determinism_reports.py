"""Compare exactly one Windows, Linux, and macOS determinism report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import cast

EXPECTED_PLATFORMS = frozenset({"Windows", "Linux", "macOS"})
EXPECTED_RELEASE = "JPPM2099001"


def _sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9A-F]{64}", value) is not None


def _valid_contract(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "source_manifest_sha256",
        "database",
        "public_export",
    }:
        return False
    database = value.get("database")
    public = value.get("public_export")
    if not isinstance(database, dict) or set(database) != {
        "logical_digest",
        "semantic_table_counts",
        "validation_checks_sha256",
    }:
        return False
    counts = database.get("semantic_table_counts")
    if (
        not isinstance(counts, dict)
        or not counts
        or any(not isinstance(key, str) for key in counts)
        or any(not isinstance(count, int) or count < 0 for count in counts.values())
    ):
        return False
    if not isinstance(public, dict) or set(public) != {
        "tree_sha256",
        "object_count",
        "total_bytes",
    }:
        return False
    return (
        _sha256(value.get("source_manifest_sha256"))
        and _sha256(database.get("logical_digest"))
        and _sha256(database.get("validation_checks_sha256"))
        and _sha256(public.get("tree_sha256"))
        and isinstance(public.get("object_count"), int)
        and int(public["object_count"]) > 0
        and isinstance(public.get("total_bytes"), int)
        and int(public["total_bytes"]) >= 0
    )


def _read_report(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("determinism report must be a JSON object")
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("release_id") != EXPECTED_RELEASE
        or payload.get("valid") is not True
    ):
        raise RuntimeError("determinism report is not a valid schema 1.0 report")
    if payload.get("platform") not in EXPECTED_PLATFORMS:
        raise RuntimeError("determinism report has no platform")
    if not _valid_contract(payload.get("stable_contract")):
        raise RuntimeError("determinism report has no stable contract")
    return cast(dict[str, object], payload)


def compare_reports(paths: list[Path]) -> dict[str, object]:
    if len(paths) != 3:
        raise RuntimeError(f"expected exactly three determinism reports, found {len(paths)}")
    reports = [_read_report(path) for path in paths]
    platforms = [str(report["platform"]) for report in reports]
    if len(set(platforms)) != 3 or set(platforms) != EXPECTED_PLATFORMS:
        raise RuntimeError("reports must contain Windows, Linux, and macOS exactly once")
    baseline = reports[0]["stable_contract"]
    mismatches = sorted(
        platform
        for platform, report in zip(platforms, reports, strict=True)
        if report["stable_contract"] != baseline
    )
    if mismatches:
        raise RuntimeError("stable determinism contract differs on: " + ", ".join(mismatches))
    return {
        "schema_version": "1.0",
        "ready": True,
        "platforms": sorted(platforms),
        "stable_contract": baseline,
    }


def _report_paths(positional: list[Path], directory: Path | None) -> list[Path]:
    if bool(positional) == bool(directory):
        raise RuntimeError("provide either three reports or --directory")
    if directory is not None:
        return sorted(path for path in directory.rglob("*.json") if path.is_file())
    return positional


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", type=Path, nargs="*")
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    result = compare_reports(_report_paths(args.reports, args.directory))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
