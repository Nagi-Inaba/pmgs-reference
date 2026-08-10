"""Structural, hash, coverage, and leakage checks for a public export tree."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

from lxml import html

from pmgs_reference.publication.model import canonical_json_bytes
from pmgs_reference.store import JSONDict

_LOCAL_PATH = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|[\\/](?:users|home)[\\/])")
_LOCAL_PATH_JSON = re.compile(r"(?i)(?<![a-z0-9])(?:[a-z]:(?:/|\\\\)|[\\/](?:users|home)[\\/])")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:password|passwd|access[_-]?token|api[_-]?key|client[_-]?secret)\s*[:=]\s*[^\s,;]+"
)
_FORBIDDEN_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".csv", ".pdf", ".zip", ".xsl"}
_VALIDATION_WORKERS = 32
_VALIDATION_WINDOW = 128


@dataclass(frozen=True, slots=True)
class PublicValidationResult:
    valid: bool
    release_id: str | None
    object_count: int
    total_bytes: int
    missing_objects: tuple[str, ...]
    unexpected_objects: tuple[str, ...]
    metadata_errors: tuple[str, ...]
    parse_errors: tuple[str, ...]
    forbidden_files: tuple[str, ...]
    leakage_errors: tuple[str, ...]
    html_errors: tuple[str, ...]
    notice_errors: tuple[str, ...]
    coverage_errors: tuple[str, ...]
    tree_sha256: str

    def as_dict(self) -> JSONDict:
        return {
            "valid": self.valid,
            "release_id": self.release_id,
            "object_count": self.object_count,
            "total_bytes": self.total_bytes,
            "missing_objects": list(self.missing_objects),
            "unexpected_objects": list(self.unexpected_objects),
            "metadata_errors": list(self.metadata_errors),
            "parse_errors": list(self.parse_errors),
            "forbidden_files": list(self.forbidden_files),
            "leakage_errors": list(self.leakage_errors),
            "html_errors": list(self.html_errors),
            "notice_errors": list(self.notice_errors),
            "coverage_errors": list(self.coverage_errors),
            "tree_sha256": self.tree_sha256,
        }


@dataclass(frozen=True, slots=True)
class _CoverageEntry:
    kind: str
    item_count: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class _FileCheck:
    key: str
    size: int
    sha256: str
    metadata_errors: tuple[str, ...]
    parse_errors: tuple[str, ...]
    forbidden_files: tuple[str, ...]
    leakage_errors: tuple[str, ...]
    html_errors: tuple[str, ...]
    notice_errors: tuple[str, ...]
    coverage_entry: _CoverageEntry | None
    coverage_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _NoticeRequirements:
    attribution: str
    source_url: str
    processing_ja: str
    processing_en: str
    non_affiliation_ja: str
    non_affiliation_en: str

    def for_key(self, key: str) -> tuple[str, ...]:
        if key == "index.html":
            language = "ja"
        elif key == "index.en.html":
            language = "en"
        elif key == "llms.txt":
            language = "ja"
        elif key == "llms.en.txt":
            language = "en"
        elif "/site/ja/" in key and key.endswith((".html", ".md")):
            language = "ja"
        elif "/site/en/" in key and key.endswith((".html", ".md")):
            language = "en"
        else:
            return ()
        processing = self.processing_en if language == "en" else self.processing_ja
        non_affiliation = self.non_affiliation_en if language == "en" else self.non_affiliation_ja
        return self.attribution, self.source_url, processing, non_affiliation


def _manifest_path(root: Path) -> Path:
    releases = root / "releases"
    candidates = sorted(
        path for path in releases.glob("*/manifest.json") if path.parent.parent == releases
    )
    if len(candidates) != 1:
        raise ValueError(f"expected one release manifest, found {len(candidates)}")
    return candidates[0]


def _object_metadata(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_objects = manifest.get("objects")
    if not isinstance(raw_objects, list):
        raise ValueError("release manifest objects must be an array")
    output: dict[str, dict[str, Any]] = {}
    for raw_object in raw_objects:
        if not isinstance(raw_object, dict) or not isinstance(raw_object.get("key"), str):
            raise ValueError("release manifest contains invalid object metadata")
        key = str(raw_object["key"])
        if key in output:
            raise ValueError(f"release manifest contains duplicate key: {key}")
        output[key] = cast(dict[str, Any], raw_object)
    return output


def _notice_requirements(
    root: Path, release_id: str
) -> tuple[_NoticeRequirements | None, str | None]:
    path = root / "releases" / release_id / "publication-policy.json"
    try:
        payload = json.loads(path.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError("root is not an object")
        sources = payload.get("sources")
        if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
            raise ValueError("v1 requires exactly one source")
        source = cast(dict[str, Any], sources[0])
        processing = source.get("processing_notice")
        non_affiliation = source.get("non_affiliation_notice")
        if not isinstance(processing, dict) or not isinstance(non_affiliation, dict):
            raise ValueError("localized notices are missing")
        values = (
            source.get("attribution"),
            source.get("source_url"),
            processing.get("ja"),
            processing.get("en"),
            non_affiliation.get("ja"),
            non_affiliation.get("en"),
        )
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("notice fields must be non-empty strings")
        return _NoticeRequirements(*cast(tuple[str, str, str, str, str, str], values)), None
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return None, f"publication policy notices are invalid: {error}"


def _validate_html(key: str, data: bytes) -> list[str]:
    errors: list[str] = []
    try:
        document = html.fromstring(data)
    except Exception as error:
        return [f"{key}: HTML parse failed: {type(error).__name__}"]
    bodies = list(document.iter("body"))
    body_text = " ".join(
        part.decode("utf-8") if isinstance(part, bytes) else part for part in document.itertext()
    )
    if not bodies or not " ".join(body_text.split()):
        errors.append(f"{key}: HTML has no readable body")
    for script in document.iter("script"):
        script_type = str(script.get("type") or "")
        source = str(script.get("src") or "")
        if script_type == "application/ld+json":
            continue
        if source == "/assets/webmcp.js":
            continue
        errors.append(f"{key}: unexpected executable script")
    for element in document.iter():
        if element.tag not in {"script", "img", "iframe", "link"}:
            continue
        attribute = "src" if element.get("src") is not None else "href"
        value = str(element.get(attribute) or "")
        relation = str(element.get("rel") or "")
        if value.startswith(("http://", "https://")) and relation not in {
            "alternate",
            "canonical",
        }:
            errors.append(f"{key}: unexpected external resource URL")
    return errors


def _coverage_entry(key: str, payload: Any) -> tuple[_CoverageEntry | None, list[str]]:
    parts = key.split("/")
    kind: str | None = None
    count_field = ""
    if (
        len(parts) >= 5
        and parts[0] == "releases"
        and parts[2] == "groups"
        and parts[-1] == "manifest.json"
    ):
        kind = "group"
        count_field = "record_count"
    elif (
        len(parts) == 5
        and parts[0] == "releases"
        and parts[2] == "documents"
        and parts[-1] == "manifest.json"
    ):
        kind = "document"
        count_field = "segment_count"
    if kind is None:
        return None, []
    if not isinstance(payload, dict):
        return None, [f"{key}: invalid {kind} manifest"]
    chunks = payload.get("chunks")
    item_count = payload.get(count_field)
    if not isinstance(chunks, list) or not isinstance(item_count, int):
        return None, [f"{key}: invalid {kind} coverage metadata"]
    return _CoverageEntry(kind, item_count, len(chunks)), []


def _check_file(
    path: Path,
    key: str,
    metadata: dict[str, Any] | None,
    cached_data: bytes | None = None,
    required_notices: tuple[str, ...] = (),
) -> _FileCheck:
    data = path.read_bytes() if cached_data is None else cached_data
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest().upper()
    metadata_errors: list[str] = []
    parse_errors: list[str] = []
    forbidden_files: list[str] = []
    leakage_errors: list[str] = []
    html_errors: list[str] = []
    notice_errors: list[str] = []
    coverage_errors: list[str] = []
    coverage_entry: _CoverageEntry | None = None

    if metadata is not None:
        if size != int(metadata.get("bytes", -1)):
            metadata_errors.append(f"{key}: byte size mismatch")
        if sha256 != str(metadata.get("sha256", "")):
            metadata_errors.append(f"{key}: SHA-256 mismatch")

    suffix = path.suffix.lower()
    if suffix in _FORBIDDEN_SUFFIXES:
        forbidden_files.append(key)
    parsed_json: Any = None
    if suffix == ".json":
        try:
            parsed_json = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            parse_errors.append(f"{key}: JSON parse failed: {type(error).__name__}")
        if parsed_json is not None:
            coverage_entry, coverage_errors = _coverage_entry(key, parsed_json)
    elif suffix == ".xml":
        try:
            ElementTree.fromstring(data)
        except ElementTree.ParseError as error:
            parse_errors.append(f"{key}: XML parse failed: {error}")
    elif suffix == ".html":
        html_errors.extend(_validate_html(key, data))
    if suffix in {".json", ".html", ".md", ".txt", ".xml", ".css"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            parse_errors.append(f"{key}: text is not UTF-8")
        else:
            local_path_pattern = _LOCAL_PATH_JSON if suffix == ".json" else _LOCAL_PATH
            if local_path_pattern.search(text):
                leakage_errors.append(f"{key}: local absolute path detected")
            if _SECRET_ASSIGNMENT.search(text):
                leakage_errors.append(f"{key}: possible secret assignment detected")
            for required_notice in required_notices:
                if required_notice not in text:
                    notice_errors.append(f"{key}: required public notice is missing")

    return _FileCheck(
        key=key,
        size=size,
        sha256=sha256,
        metadata_errors=tuple(metadata_errors),
        parse_errors=tuple(parse_errors),
        forbidden_files=tuple(forbidden_files),
        leakage_errors=tuple(leakage_errors),
        html_errors=tuple(html_errors),
        notice_errors=tuple(notice_errors),
        coverage_entry=coverage_entry,
        coverage_errors=tuple(coverage_errors),
    )


def _coverage_checks(
    manifest: dict[str, Any],
    *,
    group_count: int,
    group_records: int,
    group_chunks: int,
    document_count: int,
    document_segments: int,
    document_chunks: int,
) -> list[str]:
    errors: list[str] = []
    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict):
        return ["release manifest coverage is not an object"]
    if group_records != int(coverage.get("classification.storage_records", -1)):
        errors.append("classification storage record coverage does not match group manifests")
    if group_count != int(coverage.get("classification.groups", -1)):
        errors.append("classification group coverage does not match group manifests")
    if group_chunks != int(coverage.get("classification.chunks", -1)):
        errors.append("classification chunk coverage does not match group manifests")
    if document_count != int(coverage.get("documents.total", -1)):
        errors.append("document coverage does not match document manifests")
    if document_segments != int(coverage.get("documents.segments", -1)):
        errors.append("document segment coverage does not match document manifests")
    if document_chunks != int(coverage.get("documents.chunks", -1)):
        errors.append("document chunk coverage does not match document manifests")
    return errors


def validate_public_export(root: Path) -> PublicValidationResult:
    """Validate a complete local public candidate without contacting external services."""
    root = root.resolve()
    manifest_path = _manifest_path(root)
    manifest_data = manifest_path.read_bytes()
    manifest_raw = json.loads(manifest_data)
    if not isinstance(manifest_raw, dict):
        raise ValueError("release manifest is not an object")
    manifest = cast(dict[str, Any], manifest_raw)
    release_id = str(manifest.get("release_id", ""))
    notice_requirements, notice_policy_error = _notice_requirements(root, release_id)
    objects = _object_metadata(manifest)
    manifest_key = manifest_path.relative_to(root).as_posix()
    expected = set(objects) | {manifest_key}
    actual_paths = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    actual = {path.relative_to(root).as_posix() for path in actual_paths}
    missing = tuple(sorted(expected - actual))
    unexpected = tuple(sorted(actual - expected))

    metadata_errors: list[str] = []
    parse_errors: list[str] = []
    forbidden_files: list[str] = []
    leakage_errors: list[str] = []
    html_errors: list[str] = []
    notice_errors: list[str] = []
    if notice_policy_error is not None:
        notice_errors.append(notice_policy_error)
    coverage_errors: list[str] = []
    total_bytes = 0
    group_count = 0
    group_records = 0
    group_chunks = 0
    document_count = 0
    document_segments = 0
    document_chunks = 0
    tree_digest = hashlib.sha256()

    def accept(check: _FileCheck) -> None:
        nonlocal total_bytes
        nonlocal group_count, group_records, group_chunks
        nonlocal document_count, document_segments, document_chunks
        total_bytes += check.size
        metadata_errors.extend(check.metadata_errors)
        parse_errors.extend(check.parse_errors)
        forbidden_files.extend(check.forbidden_files)
        leakage_errors.extend(check.leakage_errors)
        html_errors.extend(check.html_errors)
        notice_errors.extend(check.notice_errors)
        coverage_errors.extend(check.coverage_errors)
        if check.coverage_entry is not None:
            if check.coverage_entry.kind == "group":
                group_count += 1
                group_records += check.coverage_entry.item_count
                group_chunks += check.coverage_entry.chunk_count
            else:
                document_count += 1
                document_segments += check.coverage_entry.item_count
                document_chunks += check.coverage_entry.chunk_count
        key_bytes = check.key.encode("utf-8")
        tree_digest.update(len(key_bytes).to_bytes(4, "big"))
        tree_digest.update(key_bytes)
        tree_digest.update(bytes.fromhex(check.sha256))

    pending: deque[Future[_FileCheck]] = deque()
    with ThreadPoolExecutor(max_workers=_VALIDATION_WORKERS) as executor:
        for path in actual_paths:
            key = path.relative_to(root).as_posix()
            pending.append(
                executor.submit(
                    _check_file,
                    path,
                    key,
                    objects.get(key),
                    manifest_data if path == manifest_path else None,
                    notice_requirements.for_key(key) if notice_requirements is not None else (),
                )
            )
            if len(pending) >= _VALIDATION_WINDOW:
                accept(pending.popleft().result())
        while pending:
            accept(pending.popleft().result())

    coverage_errors.extend(
        _coverage_checks(
            manifest,
            group_count=group_count,
            group_records=group_records,
            group_chunks=group_chunks,
            document_count=document_count,
            document_segments=document_segments,
            document_chunks=document_chunks,
        )
    )
    valid = not any(
        (
            missing,
            unexpected,
            metadata_errors,
            parse_errors,
            forbidden_files,
            leakage_errors,
            html_errors,
            notice_errors,
            coverage_errors,
        )
    )
    return PublicValidationResult(
        valid=valid,
        release_id=str(manifest.get("release_id")) if manifest.get("release_id") else None,
        object_count=len(actual_paths),
        total_bytes=total_bytes,
        missing_objects=missing,
        unexpected_objects=unexpected,
        metadata_errors=tuple(metadata_errors),
        parse_errors=tuple(parse_errors),
        forbidden_files=tuple(forbidden_files),
        leakage_errors=tuple(leakage_errors),
        html_errors=tuple(html_errors),
        notice_errors=tuple(notice_errors),
        coverage_errors=tuple(coverage_errors),
        tree_sha256=tree_digest.hexdigest().upper(),
    )


def write_public_validation_report(result: PublicValidationResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(result.as_dict()))
    temporary.replace(path)
