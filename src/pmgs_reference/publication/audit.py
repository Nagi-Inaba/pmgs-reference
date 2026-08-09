"""Reproducibility and release-readiness audit for two validated public exports."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pmgs_reference.publication.model import canonical_json_bytes
from pmgs_reference.schema import APPLICATION_ID
from pmgs_reference.store import JSONDict

_SHA256 = re.compile(r"^[A-F0-9]{64}$")
_TRUE_DELIVERY = (
    "web_information_service",
    "api_record_lookup",
    "mcp_record_lookup",
    "search_indexing",
    "ai_input",
)
_FALSE_DELIVERY = (
    "ai_training",
    "source_archive_download",
    "canonical_database_download",
)
_VALIDATION_ERROR_FIELDS = (
    "missing_objects",
    "unexpected_objects",
    "metadata_errors",
    "parse_errors",
    "forbidden_files",
    "leakage_errors",
    "html_errors",
    "notice_errors",
    "coverage_errors",
)


@dataclass(frozen=True, slots=True)
class _ManifestStats:
    manifest_sha256: str
    manifest_bytes: int
    release_id: str
    source_manifest_sha256: str
    database_schema_version: int
    generated_at: str
    base_url: str
    publication_policy_sha256: str
    object_count: int
    total_bytes: int
    chunk_object_count: int
    max_json_chunk_bytes: int
    largest_chunk_bytes: int
    oversized_chunk_count: int
    largest_object_key: str
    largest_object_bytes: int
    duplicate_object_keys: int
    coverage_group_count: int
    coverage_document_count: int
    coverage_chunk_count: int
    coverage_oversized_chunks: int
    policy_sha256: str
    policy_safe_delivery: bool


@dataclass(frozen=True, slots=True)
class PublicReleaseAuditResult:
    ready: bool
    release_id: str
    database_file: str
    database_size_bytes: int
    database_sha256: str
    source_manifest_sha256: str
    tree_sha256: str
    release_manifest_sha256: str
    object_count: int
    total_bytes: int
    chunk_object_count: int
    max_json_chunk_bytes: int
    largest_chunk_bytes: int
    oversized_chunk_count: int
    largest_object_key: str
    largest_object_bytes: int
    checks: dict[str, bool]
    failures: tuple[str, ...]

    def as_dict(self) -> JSONDict:
        return {
            "ready": self.ready,
            "release_id": self.release_id,
            "database_file": self.database_file,
            "database_size_bytes": self.database_size_bytes,
            "database_sha256": self.database_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
            "tree_sha256": self.tree_sha256,
            "release_manifest_sha256": self.release_manifest_sha256,
            "object_count": self.object_count,
            "total_bytes": self.total_bytes,
            "chunk_object_count": self.chunk_object_count,
            "max_json_chunk_bytes": self.max_json_chunk_bytes,
            "largest_chunk_bytes": self.largest_chunk_bytes,
            "oversized_chunk_count": self.oversized_chunk_count,
            "largest_object_key": self.largest_object_key,
            "largest_object_bytes": self.largest_object_bytes,
            "checks": cast(JSONDict, self.checks),
            "failures": list(self.failures),
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    return cast(dict[str, Any], payload)


def _required_sha256(value: str, name: str) -> str:
    normalized = value.strip().upper()
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256 value")
    return normalized


def _is_chunk_key(key: str) -> bool:
    name = key.rsplit("/", maxsplit=1)[-1]
    return (
        len(name) == 8
        and name[:3].isdigit()
        and name.endswith(".json")
        and ("/groups/" in key or "/documents/" in key)
    )


def _policy_is_safe(payload: dict[str, Any]) -> bool:
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return False
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("delivery"), dict):
            return False
        delivery = cast(dict[str, Any], source["delivery"])
        if any(delivery.get(key) is not True for key in _TRUE_DELIVERY):
            return False
        if any(delivery.get(key) is not False for key in _FALSE_DELIVERY):
            return False
    return True


def _manifest_stats(root: Path, export_report: dict[str, Any]) -> _ManifestStats:
    release_id = str(export_report.get("release_id", ""))
    manifest_path = root / "releases" / release_id / "manifest.json"
    manifest_data = manifest_path.read_bytes()
    manifest = json.loads(manifest_data)
    if not isinstance(manifest, dict):
        raise ValueError(f"release manifest is not an object: {root.name}")
    raw_objects = manifest.get("objects")
    coverage = manifest.get("coverage")
    if not isinstance(raw_objects, list) or not isinstance(coverage, dict):
        raise ValueError(f"release manifest is incomplete: {root.name}")
    objects: list[dict[str, Any]] = []
    for item in raw_objects:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError(f"release manifest has invalid object metadata: {root.name}")
        objects.append(cast(dict[str, Any], item))
    keys = [str(item["key"]) for item in objects]
    chunks = [item for item in objects if _is_chunk_key(str(item["key"]))]
    max_json_chunk_bytes = int(manifest.get("max_json_chunk_bytes", -1))
    manifest_key = f"releases/{release_id}/manifest.json"
    largest_object_key = manifest_key
    largest_object_bytes = len(manifest_data)
    for item in objects:
        item_bytes = int(item.get("bytes", -1))
        if item_bytes > largest_object_bytes:
            largest_object_key = str(item["key"])
            largest_object_bytes = item_bytes
    policy_path = root / "releases" / release_id / "publication-policy.json"
    policy_data = policy_path.read_bytes()
    policy = json.loads(policy_data)
    if not isinstance(policy, dict):
        raise ValueError(f"publication policy is not an object: {root.name}")
    return _ManifestStats(
        manifest_sha256=hashlib.sha256(manifest_data).hexdigest().upper(),
        manifest_bytes=len(manifest_data),
        release_id=str(manifest.get("release_id", "")),
        source_manifest_sha256=str(manifest.get("source_manifest_sha256", "")),
        database_schema_version=int(manifest.get("database_schema_version", -1)),
        generated_at=str(manifest.get("generated_at", "")),
        base_url=str(manifest.get("base_url", "")),
        publication_policy_sha256=str(manifest.get("publication_policy_sha256", "")),
        object_count=len(objects) + 1,
        total_bytes=sum(int(item.get("bytes", -1)) for item in objects) + len(manifest_data),
        chunk_object_count=len(chunks),
        max_json_chunk_bytes=max_json_chunk_bytes,
        largest_chunk_bytes=max((int(item.get("bytes", -1)) for item in chunks), default=0),
        oversized_chunk_count=sum(
            int(item.get("bytes", -1)) > max_json_chunk_bytes for item in chunks
        ),
        largest_object_key=largest_object_key,
        largest_object_bytes=largest_object_bytes,
        duplicate_object_keys=len(keys) - len(set(keys)),
        coverage_group_count=int(coverage.get("classification.groups", -1)),
        coverage_document_count=int(coverage.get("documents.total", -1)),
        coverage_chunk_count=int(coverage.get("classification.chunks", -1))
        + int(coverage.get("documents.chunks", -1)),
        coverage_oversized_chunks=int(coverage.get("json.oversized_chunks", -1)),
        policy_sha256=hashlib.sha256(policy_data).hexdigest().upper(),
        policy_safe_delivery=_policy_is_safe(cast(dict[str, Any], policy)),
    )


def _validation_matches_export(validation: dict[str, Any], export_report: dict[str, Any]) -> bool:
    return (
        validation.get("valid") is True
        and validation.get("release_id") == export_report.get("release_id")
        and validation.get("object_count") == export_report.get("object_count")
        and validation.get("total_bytes") == export_report.get("total_bytes")
        and validation.get("tree_sha256") == export_report.get("tree_sha256")
        and all(validation.get(field) == [] for field in _VALIDATION_ERROR_FIELDS)
    )


def audit_public_release(
    database: Path,
    first_root: Path,
    second_root: Path,
    first_export_report: Path,
    second_export_report: Path,
    first_validation_report: Path,
    second_validation_report: Path,
    *,
    expected_database_sha256: str,
    expected_source_manifest_sha256: str,
    report_path: Path | None = None,
) -> PublicReleaseAuditResult:
    """Audit two complete public exports and fail closed on any mismatch."""
    expected_database_sha256 = _required_sha256(
        expected_database_sha256, "expected_database_sha256"
    )
    expected_source_manifest_sha256 = _required_sha256(
        expected_source_manifest_sha256, "expected_source_manifest_sha256"
    )
    database = database.resolve()
    first_root = first_root.resolve()
    second_root = second_root.resolve()
    first_export = _json_object(first_export_report.resolve())
    second_export = _json_object(second_export_report.resolve())
    first_validation = _json_object(first_validation_report.resolve())
    second_validation = _json_object(second_validation_report.resolve())
    first_manifest = _manifest_stats(first_root, first_export)
    second_manifest = _manifest_stats(second_root, second_export)
    database_sha256 = _sha256_file(database)
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    try:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        release_row = connection.execute(
            "SELECT release_id, source_manifest_sha256 FROM release"
        ).fetchone()
    finally:
        connection.close()
    database_release = str(release_row[0]) if release_row is not None else ""
    database_source_manifest = str(release_row[1]) if release_row is not None else ""

    checks = {
        "exports.distinct_roots": first_root != second_root,
        "database.application_id": application_id == APPLICATION_ID,
        "database.hash": database_sha256 == expected_database_sha256,
        "database.release": database_release
        == first_export.get("release_id")
        == second_export.get("release_id"),
        "database.schema": user_version
        == first_manifest.database_schema_version
        == second_manifest.database_schema_version,
        "database.source_manifest": database_source_manifest.upper()
        == expected_source_manifest_sha256,
        "exports.equal": first_export == second_export,
        "validations.equal": first_validation == second_validation,
        "validations.first_ready": _validation_matches_export(first_validation, first_export),
        "validations.second_ready": _validation_matches_export(second_validation, second_export),
        "manifests.hash_equal": first_manifest.manifest_sha256 == second_manifest.manifest_sha256,
        "manifests.hash_matches_report": first_manifest.manifest_sha256
        == first_export.get("release_manifest_sha256")
        and second_manifest.manifest_sha256 == second_export.get("release_manifest_sha256"),
        "manifests.release": first_manifest.release_id == first_export.get("release_id")
        and second_manifest.release_id == second_export.get("release_id"),
        "manifests.source_manifest": first_manifest.source_manifest_sha256.upper()
        == expected_source_manifest_sha256
        and second_manifest.source_manifest_sha256.upper() == expected_source_manifest_sha256,
        "manifests.export_metadata": first_manifest.generated_at == first_export.get("generated_at")
        and second_manifest.generated_at == second_export.get("generated_at")
        and first_manifest.base_url == first_export.get("base_url")
        and second_manifest.base_url == second_export.get("base_url")
        and first_manifest.max_json_chunk_bytes == first_export.get("max_json_chunk_bytes")
        and second_manifest.max_json_chunk_bytes == second_export.get("max_json_chunk_bytes"),
        "manifests.object_count": first_manifest.object_count == first_export.get("object_count")
        and second_manifest.object_count == second_export.get("object_count"),
        "manifests.total_bytes": first_manifest.total_bytes == first_export.get("total_bytes")
        and second_manifest.total_bytes == second_export.get("total_bytes"),
        "manifests.unique_keys": first_manifest.duplicate_object_keys == 0
        and second_manifest.duplicate_object_keys == 0,
        "coverage.report_counts": first_manifest.coverage_group_count
        == first_export.get("group_count")
        and second_manifest.coverage_group_count == second_export.get("group_count")
        and first_manifest.coverage_document_count == first_export.get("document_count")
        and second_manifest.coverage_document_count == second_export.get("document_count"),
        "chunks.count": first_manifest.chunk_object_count
        == first_manifest.coverage_chunk_count
        == int(first_export.get("classification_chunk_count", -1))
        + int(first_export.get("document_chunk_count", -1))
        and second_manifest.chunk_object_count
        == second_manifest.coverage_chunk_count
        == int(second_export.get("classification_chunk_count", -1))
        + int(second_export.get("document_chunk_count", -1)),
        "chunks.max_setting": first_manifest.max_json_chunk_bytes
        == int(first_export.get("max_json_chunk_bytes", -1))
        and second_manifest.max_json_chunk_bytes
        == int(second_export.get("max_json_chunk_bytes", -1)),
        "chunks.largest_within_limit": first_manifest.largest_chunk_bytes
        <= first_manifest.max_json_chunk_bytes
        and second_manifest.largest_chunk_bytes <= second_manifest.max_json_chunk_bytes,
        "chunks.limit": first_manifest.oversized_chunk_count
        == first_manifest.coverage_oversized_chunks
        == int(first_export.get("oversized_chunk_count", -1))
        == 0
        and second_manifest.oversized_chunk_count
        == second_manifest.coverage_oversized_chunks
        == int(second_export.get("oversized_chunk_count", -1))
        == 0,
        "policy.hash": first_manifest.policy_sha256 == first_manifest.publication_policy_sha256
        and second_manifest.policy_sha256 == second_manifest.publication_policy_sha256,
        "policy.safe_delivery": first_manifest.policy_safe_delivery
        and second_manifest.policy_safe_delivery,
    }
    failures = tuple(name for name, passed in checks.items() if not passed)
    result = PublicReleaseAuditResult(
        ready=not failures,
        release_id=str(first_export.get("release_id", "")),
        database_file=database.name,
        database_size_bytes=database.stat().st_size,
        database_sha256=database_sha256,
        source_manifest_sha256=expected_source_manifest_sha256,
        tree_sha256=str(first_export.get("tree_sha256", "")),
        release_manifest_sha256=first_manifest.manifest_sha256,
        object_count=first_manifest.object_count,
        total_bytes=first_manifest.total_bytes,
        chunk_object_count=first_manifest.chunk_object_count,
        max_json_chunk_bytes=first_manifest.max_json_chunk_bytes,
        largest_chunk_bytes=first_manifest.largest_chunk_bytes,
        oversized_chunk_count=first_manifest.oversized_chunk_count,
        largest_object_key=first_manifest.largest_object_key,
        largest_object_bytes=first_manifest.largest_object_bytes,
        checks=checks,
        failures=failures,
    )
    if report_path is not None:
        path = report_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(canonical_json_bytes(result.as_dict()))
        temporary.replace(path)
    return result
