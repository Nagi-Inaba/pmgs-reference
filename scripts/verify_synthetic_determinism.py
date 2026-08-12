"""Build and validate one cross-platform synthetic determinism report."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Final

import pymupdf

from pmgs_reference.ingest.build import build_database
from pmgs_reference.publication.export import export_public
from pmgs_reference.publication.validation import validate_public_export
from pmgs_reference.validation import validate_database

RELEASE_ID: Final = "JPPM2099001"
BASE_URL: Final = "https://pmgs.example.test"
SEMANTIC_TABLES: Final = (
    "concept",
    "concept_revision",
    "concept_text",
    "concept_property",
    "relation",
    "revision_relation",
    "document",
    "document_text",
    "document_link",
    "document_revision_link",
    "reference_entry",
    "build_issue",
)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest().upper()


def _platform_name(system: str | None = None) -> str:
    current = system or platform.system()
    names = {"Windows": "Windows", "Linux": "Linux", "Darwin": "macOS"}
    try:
        return names[current]
    except KeyError as exc:
        raise RuntimeError(f"unsupported determinism platform: {current}") from exc


def _copy_synthetic_source(source: Path, target: Path) -> None:
    shutil.copytree(source, target)
    pdf_path = target / "REFERENCE" / "IPC_TEIGI" / "G06F3-048.pdf"
    pdf_path.parent.mkdir(parents=True)
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic IPC definition G06F3/048")
        document.set_metadata({})
        document.save(pdf_path, no_new_id=True, reproducible=True)  # type: ignore[no-untyped-call]
    finally:
        document.close()  # type: ignore[no-untyped-call]


def build_report(
    source: Path, policy: Path, *, platform_name: str | None = None
) -> dict[str, object]:
    """Build fresh artifacts and return only measured deterministic evidence."""
    with tempfile.TemporaryDirectory(prefix="pmgs-determinism-") as temporary_name:
        temporary = Path(temporary_name)
        source_copy = temporary / RELEASE_ID
        _copy_synthetic_source(source.resolve(), source_copy)
        database = temporary / "pmgs.sqlite"
        public_root = temporary / "public"

        build = build_database(source_copy, RELEASE_ID, database)
        validation = validate_database(database)
        if not validation.valid:
            raise RuntimeError("synthetic database validation failed")
        if build.logical_digest != validation.logical_digest:
            raise RuntimeError("build and validation logical digests differ")

        export = export_public(
            database,
            policy.resolve(),
            public_root,
            base_url=BASE_URL,
        )
        public_validation = validate_public_export(public_root)
        if not public_validation.valid:
            raise RuntimeError("synthetic public export validation failed")
        if (
            export.tree_sha256 != public_validation.tree_sha256
            or export.object_count != public_validation.object_count
            or export.total_bytes != public_validation.total_bytes
        ):
            raise RuntimeError("public export and validation measurements differ")

        semantic_counts = {name: validation.counts[name] for name in SEMANTIC_TABLES}
        stable_contract = {
            "source_manifest_sha256": build.source_manifest_sha256,
            "database": {
                "logical_digest": validation.logical_digest,
                "semantic_table_counts": semantic_counts,
                "validation_checks_sha256": _sha256(validation.checks),
            },
            "public_export": {
                "tree_sha256": public_validation.tree_sha256,
                "object_count": public_validation.object_count,
                "total_bytes": public_validation.total_bytes,
            },
        }
        return {
            "schema_version": "1.0",
            "platform": platform_name or _platform_name(),
            "release_id": RELEASE_ID,
            "stable_contract": stable_contract,
            "valid": True,
        }


def _write_report(path: Path, report: dict[str, object]) -> None:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.tmp")
    temporary.write_bytes(_canonical_json(report))
    temporary.replace(resolved)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.source, args.policy)
    _write_report(args.output, report)
    print(_canonical_json(report).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
