"""Structural, hash, coverage, and leakage checks for a public export tree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
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
_CSS_URL = re.compile(r"(?i)url\(\s*(['\"]?)(.*?)\1\s*\)")
_CSS_IMPORT = re.compile(r"(?i)@import\s+(['\"])(.*?)\1")
_URL_ATTRIBUTES = frozenset(
    {"src", "href", "data", "action", "formaction", "poster", "background", "manifest"}
)


@dataclass(frozen=True, slots=True)
class _SafeFile:
    path: Path
    key: str
    device: int
    inode: int


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _ensure_plain_directory(path: Path, *, label: str) -> os.stat_result:
    try:
        file_stat = path.lstat()
    except OSError as error:
        raise ValueError(f"unsafe public export {label}: cannot inspect {path}: {error}") from error
    if stat.S_ISLNK(file_stat.st_mode) or _is_reparse_point(file_stat):
        raise ValueError(f"unsafe public export {label}: symbolic link or reparse point: {path}")
    if not stat.S_ISDIR(file_stat.st_mode):
        raise ValueError(f"unsafe public export {label}: not a directory: {path}")
    return file_stat


def _resolved_under_root(path: Path, root: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError(f"unsafe public export {label}: target escapes root: {path}") from error
    return resolved


def _safe_export_files(root: Path) -> tuple[Path, list[_SafeFile]]:
    lexical_root = root.absolute()
    ancestors = list(reversed((lexical_root, *lexical_root.parents)))
    for ancestor in ancestors:
        _ensure_plain_directory(ancestor, label="ancestor")
    resolved_root = lexical_root.resolve(strict=True)

    files: list[_SafeFile] = []
    pending = [lexical_root]
    while pending:
        directory = pending.pop()
        _ensure_plain_directory(directory, label="directory")
        _resolved_under_root(directory, resolved_root, label="directory")
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise ValueError(
                f"unsafe public export directory: cannot enumerate {directory}"
            ) from error
        for entry in entries:
            path = Path(entry.path)
            try:
                file_stat = path.lstat()
            except OSError as error:
                raise ValueError(f"unsafe public export object: cannot inspect {path}") from error
            if stat.S_ISLNK(file_stat.st_mode) or _is_reparse_point(file_stat):
                raise ValueError(
                    f"unsafe public export object: symbolic link or reparse point: {path}"
                )
            _resolved_under_root(path, resolved_root, label="object")
            if stat.S_ISDIR(file_stat.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"unsafe public export object: not a regular file: {path}")
            if file_stat.st_nlink != 1:
                raise ValueError(f"unsafe public export object: hard-linked file: {path}")
            files.append(
                _SafeFile(
                    path=path,
                    key=path.relative_to(lexical_root).as_posix(),
                    device=file_stat.st_dev,
                    inode=file_stat.st_ino,
                )
            )
    files.sort(key=lambda item: item.key)
    return resolved_root, files


def _read_safe_file(root: Path, safe_file: _SafeFile) -> bytes:
    try:
        before = safe_file.path.lstat()
    except OSError as error:
        raise ValueError(
            f"unsafe public export object cannot be inspected before read: {safe_file.key}"
        ) from error
    if (
        stat.S_ISLNK(before.st_mode)
        or _is_reparse_point(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (before.st_dev, before.st_ino) != (safe_file.device, safe_file.inode)
    ):
        raise ValueError(f"unsafe public export object changed before read: {safe_file.key}")
    _resolved_under_root(safe_file.path, root, label="object")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(safe_file.path, flags)
    except OSError as error:
        raise ValueError(
            f"unsafe public export object cannot be opened: {safe_file.key}"
        ) from error
    try:
        opened = os.fstat(descriptor)
        try:
            current = safe_file.path.stat(follow_symlinks=False)
        except OSError as error:
            raise ValueError(
                f"unsafe public export object changed during open: {safe_file.key}"
            ) from error
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (safe_file.device, safe_file.inode)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError(f"unsafe public export object changed during open: {safe_file.key}")
        _resolved_under_root(safe_file.path, root, label="object")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


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


def _manifest_file(files: list[_SafeFile]) -> _SafeFile:
    candidates = [
        item
        for item in files
        if len(item.key.split("/")) == 3
        and item.key.startswith("releases/")
        and item.key.endswith("/manifest.json")
    ]
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
    root: Path, release_id: str, files_by_key: dict[str, _SafeFile]
) -> tuple[_NoticeRequirements | None, str | None]:
    key = f"releases/{release_id}/publication-policy.json"
    try:
        policy_file = files_by_key[key]
        payload = json.loads(_read_safe_file(root, policy_file))
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
    except (KeyError, OSError, json.JSONDecodeError, ValueError) as error:
        return None, f"publication policy notices are invalid: {error}"


def _is_external_url(value: str) -> bool:
    stripped = value.strip()
    if any(ord(character) < 0x20 for character in stripped):
        return True
    normalized = stripped.replace("\\", "/")
    if normalized.startswith("//"):
        return True
    parsed = urlsplit(normalized)
    return bool(parsed.scheme or parsed.netloc)


def _external_css_errors(key: str, css: str) -> list[str]:
    errors: list[str] = []
    if "\\" in css:
        errors.append(f"{key}: CSS escapes are forbidden")
    if re.search(r"(?i)@import\b", css):
        errors.append(f"{key}: CSS import is forbidden")
    urls = [match.group(2) for match in _CSS_URL.finditer(css)]
    urls.extend(match.group(2) for match in _CSS_IMPORT.finditer(css))
    errors.extend(
        f"{key}: unexpected external CSS URL" for value in urls if _is_external_url(value)
    )
    if re.search(r"(?i)(?:https?:|data:|(?<!:)//)", css):
        errors.append(f"{key}: external CSS resource syntax is forbidden")
    return errors


def _attribute_local_name(name: str) -> str:
    return name.rsplit("}", maxsplit=1)[-1].rsplit(":", maxsplit=1)[-1].lower()


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
            if source:
                errors.append(f"{key}: JSON-LD script must be inline")
            try:
                json.loads(str(script.text or ""))
            except json.JSONDecodeError:
                errors.append(f"{key}: JSON-LD script is invalid")
            continue
        if source == "/assets/webmcp.js":
            continue
        errors.append(f"{key}: unexpected executable script")
    for element in document.iter():
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in {"base", "iframe", "object", "embed"}:
            errors.append(f"{key}: forbidden embedded object")
        if tag == "meta" and element.get("http-equiv") is not None:
            errors.append(f"{key}: meta HTTP directives are forbidden")
        relations = {part.lower() for part in str(element.get("rel") or "").split()}
        for raw_name, raw_value in element.attrib.items():
            attribute = _attribute_local_name(str(raw_name))
            if attribute.startswith("on"):
                errors.append(f"{key}: inline event handlers are forbidden")
                continue
            if attribute in {"ping", "srcset"}:
                errors.append(f"{key}: {attribute} is forbidden")
                continue
            if attribute not in _URL_ATTRIBUTES:
                continue
            value = str(raw_value).strip()
            if not _is_external_url(value):
                continue
            allowed_link_relation = relations == {"alternate"} or relations == {"canonical"}
            allowed_link = (
                tag == "link"
                and attribute == "href"
                and allowed_link_relation
                and urlsplit(value).scheme.lower() == "https"
                and not value.startswith("//")
            )
            allowed_anchor = (
                tag == "a"
                and attribute == "href"
                and urlsplit(value).scheme.lower() == "https"
                and not value.startswith("//")
            )
            if not (allowed_link or allowed_anchor):
                errors.append(f"{key}: unexpected external URL in {attribute}")
        css_values = [str(element.get("style") or "")]
        if tag == "style":
            css_values.append(str(element.text or ""))
        for css in css_values:
            errors.extend(_external_css_errors(key, css))
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
    safe_root: Path | None = None,
    safe_file: _SafeFile | None = None,
) -> _FileCheck:
    if cached_data is not None:
        data = cached_data
    elif safe_root is not None and safe_file is not None:
        data = _read_safe_file(safe_root, safe_file)
    else:
        data = path.read_bytes()
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
            if suffix == ".css":
                html_errors.extend(_external_css_errors(key, text))

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
    root, safe_files = _safe_export_files(root)
    files_by_key = {item.key: item for item in safe_files}
    manifest_file = _manifest_file(safe_files)
    manifest_data = _read_safe_file(root, manifest_file)
    manifest_raw = json.loads(manifest_data)
    if not isinstance(manifest_raw, dict):
        raise ValueError("release manifest is not an object")
    manifest = cast(dict[str, Any], manifest_raw)
    release_id = str(manifest.get("release_id", ""))
    notice_requirements, notice_policy_error = _notice_requirements(root, release_id, files_by_key)
    objects = _object_metadata(manifest)
    manifest_key = manifest_file.key
    expected = set(objects) | {manifest_key}
    actual = set(files_by_key)
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
        for safe_file in safe_files:
            path = safe_file.path
            key = safe_file.key
            pending.append(
                executor.submit(
                    _check_file,
                    path,
                    key,
                    objects.get(key),
                    manifest_data if safe_file == manifest_file else None,
                    notice_requirements.for_key(key) if notice_requirements is not None else (),
                    root,
                    safe_file,
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
        object_count=len(safe_files),
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
