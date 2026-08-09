"""Deterministic inventory and format validation for a PMGS package."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import pymupdf
from lxml import etree, html

from pmgs_reference.ingest.csv_support import portable_csv_field_size_limit

FileType = Literal["csv", "xml", "html", "pdf", "xsl", "text"]
ProcessingStatus = Literal["parsed", "retained", "failed"]

_XML_ENCODING = re.compile(rb"<\?xml[^>]+encoding=[\"']([^\"']+)[\"']", re.IGNORECASE)
_XML_DECLARATION_TEXT = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>", re.IGNORECASE)
_SHIFT_JIS_LABELS = {"shift_jis", "shift-jis", "shiftjis", "sjis", "x-sjis"}


@dataclass(frozen=True, slots=True)
class SourceManifestEntry:
    source_id: str
    relative_path: str
    size_bytes: int
    sha256: str
    file_type: FileType
    encoding: str | None
    data_group: str
    parser: str
    status: ProcessingStatus
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "file_type": self.file_type,
            "encoding": self.encoding,
            "data_group": self.data_group,
            "parser": self.parser,
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class SourceInventory:
    entries: tuple[SourceManifestEntry, ...]
    logical_sha256: str
    total_bytes: int

    def summary(self) -> dict[str, object]:
        status_counts = Counter(entry.status for entry in self.entries)
        type_counts = Counter(entry.file_type for entry in self.entries)
        group_counts = Counter(entry.data_group for entry in self.entries)
        return {
            "schema_version": "1.0",
            "file_count": len(self.entries),
            "total_bytes": self.total_bytes,
            "logical_sha256": self.logical_sha256,
            "status_counts": dict(sorted(status_counts.items())),
            "file_type_counts": dict(sorted(type_counts.items())),
            "data_group_counts": dict(sorted(group_counts.items())),
        }


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def _source_id(relative_path: str, content_sha256: str) -> str:
    identity = hashlib.sha256(
        relative_path.encode("utf-8") + b"\0" + content_sha256.encode("ascii")
    ).hexdigest()
    return f"src-{identity[:24]}"


def _classify(path: Path, relative_path: str) -> tuple[FileType, str, str]:
    suffix = path.suffix.lower()
    if path.name.upper() == "COPYRGHT":
        file_type: FileType = "text"
        parser = "utf-8-text"
    elif suffix == ".csv":
        file_type = "csv"
        parser = "python-csv"
    elif suffix == ".xml":
        file_type = "xml"
        parser = "lxml-xml"
    elif suffix == ".xsl":
        file_type = "xsl"
        parser = "lxml-xsl-retained"
    elif suffix in {".html", ".htm"}:
        file_type = "html"
        parser = "lxml-html"
    elif suffix == ".pdf":
        file_type = "pdf"
        parser = "pymupdf"
    else:
        raise ValueError(f"unsupported file type: {relative_path}")

    parts = relative_path.split("/")
    if len(parts) >= 3:
        data_group = "/".join(parts[:2])
    elif len(parts) >= 2:
        data_group = parts[0]
    else:
        data_group = path.name.upper()
    return file_type, data_group, parser


def _decode_text(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp932"), "cp932"


def _xml_encoding(raw: bytes) -> str | None:
    match = _XML_ENCODING.search(raw[:256])
    return match.group(1).decode("ascii", errors="replace") if match else None


def _parse_xml(raw: bytes) -> str | None:
    declared_encoding = _xml_encoding(raw)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        etree.fromstring(raw, parser=parser)
        return declared_encoding
    except etree.XMLSyntaxError:
        normalized_encoding = (declared_encoding or "").lower().replace(" ", "_")
        if normalized_encoding not in _SHIFT_JIS_LABELS:
            raise

    # Some PMGS XML declares Shift_JIS while containing Windows-31J extension
    # characters. Decode that documented legacy superset strictly, remove only
    # the now-invalid byte-encoding declaration, and keep strict XML parsing.
    text = raw.decode("cp932")
    text_without_declaration = _XML_DECLARATION_TEXT.sub("", text, count=1)
    fallback_parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    etree.fromstring(text_without_declaration, parser=fallback_parser)
    return "cp932"


def _validate(raw: bytes, file_type: FileType) -> tuple[str | None, ProcessingStatus]:
    if file_type == "csv":
        text, encoding = _decode_text(raw)
        with portable_csv_field_size_limit():
            for _row in csv.reader(io.StringIO(text, newline="")):
                pass
        return encoding, "parsed"
    if file_type in {"xml", "xsl"}:
        xml_encoding = _parse_xml(raw)
        status: ProcessingStatus = "retained" if file_type == "xsl" else "parsed"
        return xml_encoding, status
    if file_type == "html":
        _text, encoding = _decode_text(raw)
        html_parser = html.HTMLParser(recover=True)
        html.fromstring(raw, parser=html_parser)
        return encoding, "parsed"
    if file_type == "pdf":
        with pymupdf.open(stream=raw, filetype="pdf") as document:  # type: ignore[no-untyped-call]
            if document.needs_pass:
                raise ValueError("encrypted PDF")
            _ = document.page_count
        return None, "parsed"
    _text, encoding = _decode_text(raw)
    return encoding, "retained"


def _safe_error(error: Exception, source_root: Path) -> str:
    message = str(error).replace(str(source_root), "<source>")
    return f"{type(error).__name__}: {message}"[:500]


def inspect_source_file(source_root: Path, path: Path) -> SourceManifestEntry:
    relative_path = path.relative_to(source_root).as_posix()
    raw = path.read_bytes()
    content_sha256 = _sha256_bytes(raw)
    try:
        file_type, data_group, parser = _classify(path, relative_path)
        encoding, status = _validate(raw, file_type)
        error = None
    except Exception as exc:  # every input must remain visible in the manifest
        suffix = path.suffix.lower().lstrip(".")
        inferred_type = suffix if suffix in {"csv", "xml", "html", "pdf", "xsl"} else "text"
        file_type = cast(FileType, inferred_type)
        data_group = relative_path.split("/", maxsplit=1)[0]
        parser = "unresolved"
        encoding = None
        status = "failed"
        error = _safe_error(exc, source_root)
    return SourceManifestEntry(
        source_id=_source_id(relative_path, content_sha256),
        relative_path=relative_path,
        size_bytes=len(raw),
        sha256=content_sha256,
        file_type=file_type,
        encoding=encoding,
        data_group=data_group,
        parser=parser,
        status=status,
        error=error,
    )


def build_inventory(source_root: Path) -> SourceInventory:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"PMGS source directory not found: {source_root}")
    files = sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    entries = tuple(inspect_source_file(source_root, path) for path in files)
    manifest_bytes = "".join(f"{_canonical_json(entry.as_dict())}\n" for entry in entries).encode(
        "utf-8"
    )
    return SourceInventory(
        entries=entries,
        logical_sha256=_sha256_bytes(manifest_bytes),
        total_bytes=sum(entry.size_bytes for entry in entries),
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_inventory(inventory: SourceInventory, manifest_path: Path, summary_path: Path) -> None:
    manifest = "".join(f"{_canonical_json(entry.as_dict())}\n" for entry in inventory.entries)
    summary = json.dumps(inventory.summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(manifest_path, manifest)
    _atomic_write_text(summary_path, summary)
