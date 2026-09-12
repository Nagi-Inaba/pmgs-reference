"""Validate the prebuilt JSON contracts consumed by the public Worker."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from pmgs_reference.normalization import group_key
from pmgs_reference.publication.model import GroupSpec, lookup_key
from pmgs_reference.publication.policy import parse_publication_policy

_SHA256 = re.compile(r"[A-F0-9]{64}")
_CHUNK = re.compile(r"[0-9]{3}")
_DOCUMENT = re.compile(r"doc-[a-f0-9]{24}")


def _string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _nullable_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _nullable_integer(value: Any) -> bool:
    return value is None or _integer(value)


def _date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _fields(value: Any, predicate: Callable[[Any], bool], *names: str) -> bool:
    return isinstance(value, dict) and all(
        name in value and predicate(value[name]) for name in names
    )


def _array(value: Any, predicate: Callable[[Any], bool]) -> bool:
    return isinstance(value, list) and all(predicate(item) for item in value)


def _version(value: Any) -> bool:
    return _fields(value, _nullable_string, "version") and _fields(
        value, lambda item: item is None or _date(item), "valid_from", "valid_to"
    )


def _text(value: Any) -> bool:
    return (
        _fields(value, _string, "kind", "source_id", "locator")
        and isinstance(value.get("text"), str)
        and value.get("language") in ("ja", "en")
        and value.get("provenance") == "official"
    )


def _property(value: Any) -> bool:
    return (
        _fields(value, _string, "name", "source_id", "locator")
        and isinstance(value.get("value"), str)
        and "language" in value
        and value["language"] in (None, "ja", "en")
        and value.get("provenance") == "official"
    )


def _relation(value: Any) -> bool:
    return (
        _fields(value, _string, "type", "code", "source_id", "locator")
        and value.get("scheme") in ("fi", "fterm", "ipc")
        and _fields(value, _nullable_string, "edition", "version")
    )


def _source(value: Any) -> bool:
    return (
        _fields(
            value,
            _string,
            "source_id",
            "title",
            "relative_id",
            "owner",
            "original_url",
            "attribution",
            "sha256",
        )
        and _SHA256.fullmatch(value["sha256"]) is not None
    )


def _document_link(value: Any) -> bool:
    return (
        _fields(value, _string, "document_id", "kind", "title", "link_type", "source_id", "locator")
        and value.get("language") in ("ja", "en", "und")
        and _fields(value, _nullable_integer, "page_count")
    )


def _revision(value: Any) -> bool:
    return _version(value) and all(
        _array(value.get(name), predicate)
        for name, predicate in (
            ("labels", _text),
            ("texts", _text),
            ("properties", _property),
            ("relations", _relation),
            ("documents", _document_link),
            ("sources", _source),
        )
    )


def _record(value: Any, release: str, spec: GroupSpec) -> bool:
    return (
        _revision(value)
        and value.get("schema_version") == "2.0"
        and value.get("release_id") == release
        and _date(value.get("reference_date"))
        and _fields(value, _string, "lookup_key", "code", "normalized_code", "fragment")
        and value.get("scheme") in ("fi", "fterm", "ipc")
        and _fields(value, _nullable_string, "edition")
        and group_key(value["scheme"], value["normalized_code"]) == spec.group_key
        and (
            (spec.kind == "classification" and value["scheme"] in ("fi", "ipc"))
            or (spec.kind == "fterm" and value["scheme"] == "fterm")
            or (
                spec.kind == "ipc" and value["scheme"] == "ipc" and value["edition"] == spec.edition
            )
        )
        and (value["scheme"] == "ipc" or value["edition"] is None)
        and value["lookup_key"]
        == lookup_key(value["scheme"], value["edition"], value["normalized_code"])
        and value.get("record_status") in ("canonical", "reference_only")
        and value.get("match_status") in ("exact", "not_valid_at_release")
        and _array(value.get("available_versions"), _version)
        and _array(value.get("revision_records"), _revision)
        and _fields(value, _integer, "relation_count", "relation_offset", "relation_limit")
        and 1 <= value["relation_limit"] <= 200
        and _fields(value, _nullable_integer, "next_relation_offset")
        and _fields(value.get("canonical_urls"), _string, "ja")
        and ("en" not in value["canonical_urls"] or _string(value["canonical_urls"]["en"]))
    )


def _segment(value: Any) -> bool:
    return (
        _fields(value, _integer, "sequence_number")
        and _fields(value, _string, "locator", "source_locator")
        and _fields(value, _nullable_string, "heading")
        and isinstance(value.get("text"), str)
        and _array(value.get("related_classifications"), lambda item: isinstance(item, dict))
    )


@dataclass(frozen=True, slots=True)
class ChunkContract:
    key: str
    count: int
    first: str | int | None
    last: str | int | None
    pages: tuple[int, ...] | None
    size: int
    sha256: str


def inspect_public_json(
    key: str, value: Any, size: int, sha256: str
) -> tuple[ChunkContract | None, tuple[ChunkContract, ...]]:
    """Return bounded chunk summaries, raising a safe error for invalid contracts."""
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    parts = key.split("/")
    if key == "api/v1/coverage.json" or (
        len(parts) == 3 and parts[0] == "releases" and parts[2] == "coverage.json"
    ):
        if not value or not all(_integer(count) for count in value.values()):
            raise ValueError("coverage counts are malformed")
        return None, ()
    if key == "api/v1/releases.json":
        if not (
            value.get("schema_version") == "2.0"
            and _string(value.get("current_release"))
            and _array(value.get("releases"), _string)
            and value["current_release"] in value["releases"]
        ):
            raise ValueError("release catalog is malformed")
        return None, ()
    if key.endswith("/publication-policy.json"):
        policy = parse_publication_policy(value)
        if len(parts) != 3 or policy.release_id != parts[1]:
            raise ValueError("publication policy identity mismatch")
        return None, ()
    if not key.startswith("releases/"):
        return None, ()
    if (
        len(parts) < 3
        or value.get("schema_version") != "2.0"
        or value.get("release_id") != parts[1]
    ):
        raise ValueError("release schema or identity mismatch")
    if len(parts) == 3:
        if parts[2] == "manifest.json":
            _release_manifest(value)
        return None, ()
    document = parts[2] == "documents"
    if document:
        if (
            len(parts) != 5
            or _DOCUMENT.fullmatch(parts[3]) is None
            or value.get("document_id") != parts[3]
        ):
            raise ValueError("document identity mismatch")
    elif parts[2] == "groups":
        if not _fields(value, _string, "group_kind", "group_key") or not _fields(
            value, _nullable_string, "edition"
        ):
            raise ValueError("group identity is missing")
        spec = GroupSpec(value["group_kind"], value["edition"] or "", value["group_key"])
        if (
            spec.kind not in ("classification", "fterm", "ipc")
            or "/".join(parts[2:-1]) != spec.object_prefix
        ):
            raise ValueError("group identity mismatch")
    else:
        return None, ()
    if parts[-1] == "manifest.json":
        return None, _manifest_chunks(key, value, document)
    chunk_id = parts[-1].removesuffix(".json")
    if _CHUNK.fullmatch(chunk_id) is None or value.get("chunk_id") != chunk_id:
        raise ValueError("chunk identity mismatch")
    items = value.get("segments" if document else "records")
    predicate = _segment if document else lambda item: _record(item, parts[1], spec)
    if not isinstance(items, list) or not all(predicate(item) for item in items):
        raise ValueError(
            "document segments are malformed"
            if document
            else "classification records are malformed"
        )
    identities = [item["sequence_number" if document else "lookup_key"] for item in items]
    if identities != sorted(set(identities)):
        raise ValueError("chunk identities must be unique and ordered")
    pages = None
    if document:
        pages = tuple(
            sorted(
                {
                    int(match[1])
                    for item in items
                    for field in ("locator", "source_locator")
                    if (match := re.fullmatch(r"page:([1-9][0-9]*)", item[field])) is not None
                }
            )
        )
    return ChunkContract(
        key,
        len(items),
        identities[0] if items else None,
        identities[-1] if items else None,
        pages,
        size,
        sha256,
    ), ()


def _manifest_chunks(key: str, value: dict[str, Any], document: bool) -> tuple[ChunkContract, ...]:
    count_field = "segment_count" if document else "record_count"
    if not _fields(value, _integer, count_field) or not isinstance(value.get("chunks"), list):
        raise ValueError("manifest counts are malformed")
    if document and not (
        _fields(value, _string, "kind", "language", "title")
        and value.get("site_language") in ("ja", "en")
        and _fields(value, _nullable_integer, "page_count")
        and "metadata" in value
        and _source(value.get("source"))
    ):
        raise ValueError("document manifest is malformed")
    prefix = key.rsplit("/", 1)[0]
    references: list[ChunkContract] = []
    for entry in value["chunks"]:
        if not (
            _fields(entry, _string, "chunk_id", "json_key", "json_sha256")
            and _CHUNK.fullmatch(entry["chunk_id"])
            and entry["json_key"] == f"{prefix}/{entry['chunk_id']}.json"
            and _SHA256.fullmatch(entry["json_sha256"])
            and _fields(entry, _integer, count_field, "json_bytes")
        ):
            raise ValueError("manifest chunk reference is malformed")
        first_field, last_field = (
            ("first_sequence", "last_sequence")
            if document
            else ("first_lookup_key", "last_lookup_key")
        )
        predicate = _nullable_integer if document else _string
        if not _fields(entry, predicate, first_field, last_field):
            raise ValueError("manifest chunk range is malformed")
        first, last = entry[first_field], entry[last_field]
        if (first is None) != (last is None) or (first is not None and first > last):
            raise ValueError("manifest chunk range is inverted")
        if (
            references
            and first is not None
            and references[-1].last is not None
            and first <= references[-1].last
        ):
            raise ValueError("manifest chunk ranges overlap or are unordered")
        if document and not _array(entry.get("pages"), _integer):
            raise ValueError("manifest pages are malformed")
        references.append(
            ChunkContract(
                entry["json_key"],
                entry[count_field],
                first,
                last,
                tuple(entry["pages"]) if document else None,
                entry["json_bytes"],
                entry["json_sha256"],
            )
        )
    if (
        len({entry.key for entry in references}) != len(references)
        or sum(entry.count for entry in references) != value[count_field]
    ):
        raise ValueError("manifest chunk counts are inconsistent")
    return tuple(references)


def _release_manifest(value: dict[str, Any]) -> None:
    if not (
        value.get("database_schema_version") == 2
        and _date(value.get("reference_date"))
        and _fields(
            value,
            _string,
            "source_manifest_sha256",
            "publication_policy_sha256",
            "generated_at",
            "base_url",
        )
        and _SHA256.fullmatch(value["source_manifest_sha256"])
        and _SHA256.fullmatch(value["publication_policy_sha256"])
        and _fields(value, _integer, "max_json_chunk_bytes")
        and 256 <= value["max_json_chunk_bytes"] <= 8 * 1024 * 1024
        and isinstance(value.get("coverage"), dict)
        and all(_integer(count) for count in value["coverage"].values())
        and _array(
            value.get("objects"),
            lambda item: (
                _fields(item, _string, "key", "sha256", "content_type")
                and _fields(item, _integer, "bytes")
                and _SHA256.fullmatch(item["sha256"]) is not None
            ),
        )
    ):
        raise ValueError("release manifest is malformed")
    try:
        generated_at = datetime.fromisoformat(value["generated_at"])
    except ValueError as exc:
        raise ValueError("release timestamp is malformed") from exc
    if "T" not in value["generated_at"] or generated_at.tzinfo is None:
        raise ValueError("release timestamp must include time and timezone")
    origin = urlsplit(value["base_url"])
    if (
        origin.scheme not in ("http", "https")
        or not origin.netloc
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ValueError("release base URL must be an HTTP(S) origin")
