from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from pmgs_reference.ingest import csv_support
from pmgs_reference.ingest.inventory import build_inventory, write_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_is_complete_deterministic_and_public_safe(synthetic_pmgs: Path) -> None:
    first = build_inventory(synthetic_pmgs)
    second = build_inventory(synthetic_pmgs)

    assert len(first.entries) == 26
    assert first.logical_sha256 == second.logical_sha256
    assert first.total_bytes == sum(entry.size_bytes for entry in first.entries)
    assert {entry.status for entry in first.entries} == {"parsed", "retained"}
    assert {entry.file_type for entry in first.entries} == {
        "csv",
        "html",
        "pdf",
        "text",
        "xml",
        "xsl",
    }
    assert all("\\" not in entry.relative_path for entry in first.entries)
    assert all(str(synthetic_pmgs) not in json.dumps(entry.as_dict()) for entry in first.entries)


def test_inventory_entries_match_json_schema(synthetic_pmgs: Path) -> None:
    inventory = build_inventory(synthetic_pmgs)
    schema = json.loads(
        (ROOT / "schemas" / "source-manifest-entry.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    for entry in inventory.entries:
        validator.validate(entry.as_dict())


def test_write_inventory_emits_jsonl_and_summary(synthetic_pmgs: Path, tmp_path: Path) -> None:
    inventory = build_inventory(synthetic_pmgs)
    manifest_path = tmp_path / "source-manifest.jsonl"
    summary_path = tmp_path / "inventory-summary.json"

    write_inventory(inventory, manifest_path, summary_path)

    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(manifest_lines) == 26
    assert summary["file_count"] == 26
    assert summary["logical_sha256"] == inventory.logical_sha256
    assert summary["status_counts"] == {"parsed": 24, "retained": 2}


def test_csv_field_limit_is_portable_to_windows_python_312(monkeypatch) -> None:
    calls: list[int] = []

    def windows_compatible_field_size_limit(limit: int | None = None) -> int:
        if limit is None:
            return 131_072
        if limit > (1 << 31) - 1:
            raise OverflowError("Python int too large to convert to C long")
        calls.append(limit)
        return 131_072

    monkeypatch.setattr(csv_support.csv, "field_size_limit", windows_compatible_field_size_limit)

    with csv_support.portable_csv_field_size_limit():
        pass

    assert calls == [csv_support.MAXIMUM_PORTABLE_CSV_FIELD_SIZE, 131_072]


def test_inventory_accepts_cp932_extension_in_declared_shift_jis_xml(tmp_path: Path) -> None:
    source_root = tmp_path / "pmgs"
    source_file = source_root / "FI" / "FI_KAISEI_DOC" / "B60T.xml"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(
        b'<?xml version="1.0" encoding="Shift_JIS"?>\n'
        b"<data><title>" + b"\xfa\x40" + b"</title></data>\n"
    )

    inventory = build_inventory(source_root)

    assert len(inventory.entries) == 1
    assert inventory.entries[0].status == "parsed"
    assert inventory.entries[0].encoding == "cp932"
