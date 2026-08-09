"""Stable identifiers, paths, bytes, and object metadata for public exports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import quote

from pmgs_reference.store import JSONDict

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"
HTML_CONTENT_TYPE: Final = "text/html; charset=utf-8"
MARKDOWN_CONTENT_TYPE: Final = "text/markdown; charset=utf-8"
TEXT_CONTENT_TYPE: Final = "text/plain; charset=utf-8"
XML_CONTENT_TYPE: Final = "application/xml; charset=utf-8"
CSS_CONTENT_TYPE: Final = "text/css; charset=utf-8"


def canonical_json_bytes(value: object) -> bytes:
    """Serialize deterministic UTF-8 JSON with one trailing newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def path_segment(value: str) -> str:
    """Encode one URL and object-key segment without treating punctuation as structure."""
    return quote(value, safe="-._~")


def fragment_id(scheme: str, edition: str | None, code: str) -> str:
    """Create a collision-safe HTML fragment using UTF-8 byte escapes."""
    prefix = scheme if edition is None else f"{scheme}-{edition}"
    raw = f"{prefix}-{code}"
    parts: list[str] = []
    for byte in raw.encode("utf-8"):
        character = chr(byte)
        if character.isascii() and (character.isalnum() or character == "-"):
            parts.append(character)
        else:
            parts.append(f"_{byte:02X}")
    return "".join(parts)


def lookup_key(scheme: str, edition: str | None, normalized_code: str) -> str:
    """Return the sortable, non-parsed lookup identity used by Worker manifests."""
    return f"{scheme}\x1f{edition or ''}\x1f{normalized_code}"


@dataclass(frozen=True, order=True, slots=True)
class GroupSpec:
    """One deterministic public classification grouping."""

    kind: str
    edition: str
    group_key: str

    @property
    def object_prefix(self) -> str:
        group = path_segment(self.group_key)
        if self.kind == "ipc":
            return f"groups/ipc/{path_segment(self.edition)}/{group}"
        return f"groups/{self.kind}/{group}"

    def site_path(self, language: str, chunk_id: str) -> str:
        group = path_segment(self.group_key)
        if self.kind == "ipc":
            base = f"/{language}/ipc/{path_segment(self.edition)}/{group}"
        else:
            base = f"/{language}/{self.kind}/{group}"
        return base if chunk_id == "001" else f"{base}/{chunk_id}"

    def site_key(self, language: str, chunk_id: str, suffix: str) -> str:
        group = path_segment(self.group_key)
        if self.kind == "ipc":
            prefix = f"site/{language}/ipc/{path_segment(self.edition)}/{group}"
        else:
            prefix = f"site/{language}/{self.kind}/{group}"
        return f"{prefix}/{chunk_id}.{suffix}"


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    bytes: int
    sha256: str
    content_type: str

    def as_dict(self) -> JSONDict:
        return {
            "key": self.key,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }


class OutputWriter:
    """Write unique object keys and retain their deterministic metadata."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects: list[ObjectMetadata] = []
        self._keys: set[str] = set()
        self._directories: set[Path] = set()

    def merge(self, other: OutputWriter) -> None:
        """Merge metadata from an isolated writer that targeted the same tree."""
        if other.root != self.root:
            raise ValueError("cannot merge public writers with different roots")
        duplicates = self._keys & other._keys
        if duplicates:
            raise ValueError(f"duplicate public object key: {min(duplicates)}")
        self._keys.update(other._keys)
        self._directories.update(other._directories)
        self.objects.extend(other.objects)

    @staticmethod
    def _validated_key(key: str) -> str:
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts or "\\" in key or not pure.parts:
            raise ValueError(f"unsafe public object key: {key}")
        return pure.as_posix()

    def write_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        *,
        record: bool = True,
    ) -> ObjectMetadata:
        clean_key = self._validated_key(key)
        if clean_key in self._keys:
            raise ValueError(f"duplicate public object key: {clean_key}")
        self._keys.add(clean_key)
        target = self.root.joinpath(*PurePosixPath(clean_key).parts)
        if target.parent not in self._directories:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._directories.add(target.parent)
        target.write_bytes(data)
        metadata = ObjectMetadata(
            key=clean_key,
            bytes=len(data),
            sha256=sha256_bytes(data),
            content_type=content_type,
        )
        if record:
            self.objects.append(metadata)
        return metadata

    def write_json(self, key: str, payload: object, *, record: bool = True) -> ObjectMetadata:
        return self.write_bytes(
            key, canonical_json_bytes(payload), JSON_CONTENT_TYPE, record=record
        )

    def write_text(
        self,
        key: str,
        text: str,
        content_type: str,
        *,
        record: bool = True,
    ) -> ObjectMetadata:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.endswith("\n"):
            normalized += "\n"
        return self.write_bytes(key, normalized.encode("utf-8"), content_type, record=record)


def chunk_json_bytes(
    header: JSONDict, record_bytes: list[bytes], *, array_key: str = "records"
) -> bytes:
    """Build exact canonical bytes without repeatedly serializing an expanding array."""
    marker = "__PMGS_RECORDS_MARKER__"
    payload = {**header, array_key: marker}
    template = canonical_json_bytes(payload)
    quoted_marker = json.dumps(marker).encode("ascii")
    prefix, suffix = template.split(quoted_marker, maxsplit=1)
    return prefix + b"[" + b",".join(record_bytes) + b"]" + suffix
