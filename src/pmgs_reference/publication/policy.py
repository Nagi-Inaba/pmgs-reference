"""Publication policy loading and fail-closed release authorization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import yaml

from pmgs_reference.publication.model import canonical_json_bytes, sha256_bytes
from pmgs_reference.store import JSONDict, JSONValue

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHA256 = re.compile(r"^[A-F0-9]{64}$")
_REQUIRED_TRUE = (
    "web_information_service",
    "api_record_lookup",
    "mcp_record_lookup",
    "search_indexing",
    "ai_input",
)
_REQUIRED_FALSE = (
    "ai_training",
    "source_archive_download",
    "canonical_database_download",
)


@dataclass(frozen=True, slots=True)
class SourcePresentation:
    owner: str
    source_url: str
    attribution: str
    processing_notice_ja: str
    processing_notice_en: str
    non_affiliation_notice_ja: str
    non_affiliation_notice_en: str

    def processing_notice(self, language: str) -> str:
        return self.processing_notice_en if language == "en" else self.processing_notice_ja

    def non_affiliation_notice(self, language: str) -> str:
        return (
            self.non_affiliation_notice_en if language == "en" else self.non_affiliation_notice_ja
        )


@dataclass(frozen=True, slots=True)
class PublicationPolicy:
    payload: JSONDict
    release_id: str
    source: SourcePresentation
    generated_at: str
    sha256: str

    @property
    def attribution(self) -> str:
        return self.source.attribution


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"publication policy {field} must be an object")
    return cast(dict[str, Any], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"publication policy {field} must be a non-empty string")
    return value.strip()


def _http_url(value: object, field: str) -> str:
    url = _string(value, field)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"publication policy {field} must be an HTTP(S) URL")
    return url


def _localized_notice(source: dict[str, Any], field: str, source_index: int) -> tuple[str, str]:
    notices = _mapping(source.get(field), f"sources[{source_index}].{field}")
    if set(notices) != {"ja", "en"}:
        raise ValueError(f"publication policy {field} must contain exactly ja and en")
    return (
        _string(notices.get("ja"), f"sources[{source_index}].{field}.ja"),
        _string(notices.get("en"), f"sources[{source_index}].{field}.en"),
    )


def load_publication_policy(path: Path) -> PublicationPolicy:
    """Load public, non-secret policy metadata and require all v1 delivery gates."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = _mapping(raw, "root")
    if root.get("schema_version") != "1.0":
        raise ValueError("unsupported publication policy schema_version")
    release_id = _string(root.get("release_id"), "release_id")
    raw_sources = root.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != 1:
        raise ValueError("publication policy v1 requires exactly one source")

    checked_dates: list[str] = []
    clean_sources: list[JSONValue] = []
    presentation: SourcePresentation | None = None
    for index, raw_source in enumerate(raw_sources):
        source = _mapping(raw_source, f"sources[{index}]")
        if source.get("acquisition_basis") != "registered_bulk_download":
            raise ValueError("publication policy acquisition_basis is not registered_bulk_download")
        if source.get("policy_status") != "registered_use":
            raise ValueError("publication policy is not enabled for registered use")
        delivery = _mapping(source.get("delivery"), f"sources[{index}].delivery")
        for name in _REQUIRED_TRUE:
            if delivery.get(name) is not True:
                raise ValueError(f"publication delivery is not enabled: {name}")
        for name in _REQUIRED_FALSE:
            if delivery.get(name) is not False:
                raise ValueError(f"publication delivery must remain disabled: {name}")

        attribution = _string(source.get("attribution"), f"sources[{index}].attribution")
        owner = _string(source.get("owner"), f"sources[{index}].owner")
        source_url = _http_url(source.get("source_url"), f"sources[{index}].source_url")
        evidence_url = _http_url(source.get("evidence_url"), f"sources[{index}].evidence_url")
        processing_ja, processing_en = _localized_notice(source, "processing_notice", index)
        non_affiliation_ja, non_affiliation_en = _localized_notice(
            source, "non_affiliation_notice", index
        )
        evidence_sha = _string(
            source.get("evidence_sha256"), f"sources[{index}].evidence_sha256"
        ).upper()
        if not _SHA256.fullmatch(evidence_sha):
            raise ValueError("publication policy evidence_sha256 is invalid")
        checked_at = _string(source.get("checked_at"), f"sources[{index}].checked_at")
        if not _DATE.fullmatch(checked_at):
            raise ValueError("publication policy checked_at must be YYYY-MM-DD")
        checked_dates.append(checked_at)

        clean_sources.append(
            {
                "source_id": _string(source.get("source_id"), f"sources[{index}].source_id"),
                "owner": owner,
                "acquisition_basis": "registered_bulk_download",
                "policy_status": "registered_use",
                "delivery": {
                    name: bool(delivery[name]) for name in (*_REQUIRED_TRUE, *_REQUIRED_FALSE)
                },
                "attribution": attribution,
                "source_url": source_url,
                "processing_notice": {"ja": processing_ja, "en": processing_en},
                "non_affiliation_notice": {
                    "ja": non_affiliation_ja,
                    "en": non_affiliation_en,
                },
                "evidence_url": evidence_url,
                "evidence_sha256": evidence_sha,
                "checked_at": checked_at,
            }
        )
        presentation = SourcePresentation(
            owner=owner,
            source_url=source_url,
            attribution=attribution,
            processing_notice_ja=processing_ja,
            processing_notice_en=processing_en,
            non_affiliation_notice_ja=non_affiliation_ja,
            non_affiliation_notice_en=non_affiliation_en,
        )

    payload: JSONDict = {
        "schema_version": "1.0",
        "release_id": release_id,
        "sources": clean_sources,
    }
    canonical = canonical_json_bytes(payload)
    if presentation is None:  # pragma: no cover - guarded by the exact-one check above
        raise ValueError("publication policy source presentation is unavailable")
    return PublicationPolicy(
        payload=payload,
        release_id=release_id,
        source=presentation,
        generated_at=f"{max(checked_dates)}T00:00:00Z",
        sha256=sha256_bytes(canonical),
    )
