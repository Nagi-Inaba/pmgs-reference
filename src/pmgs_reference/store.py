"""Read-only Python query API for a canonical PMGS Reference database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Final, Literal, cast

from pmgs_reference.data_paths import resolve_database
from pmgs_reference.errors import (
    DocumentNotFoundError,
    EditionNotFoundError,
    PMGSQueryError,
    ReleaseNotFoundError,
)
from pmgs_reference.normalization import SUPPORTED_SCHEMES, normalize_code
from pmgs_reference.schema import APPLICATION_ID, DATABASE_USER_VERSION, SCHEMA_VERSION
from pmgs_reference.store_types import JSONDict as JSONDict
from pmgs_reference.store_types import JSONValue as JSONValue

Language = Literal["ja", "en"]
ContentType = Literal["classification", "document"]

_SUPPORTED_LANGUAGES: Final = frozenset({"ja", "en"})
_SUPPORTED_CONTENT_TYPES: Final = frozenset({"classification", "document"})
_IPC_EDITION_PRIORITY: Final = ("8U", "8B", "7", "7E", "6", "5", "4")
_MAX_LIMIT: Final = 100
_DEFAULT_RELATION_LIMIT: Final = 50
_MAX_RELATION_LIMIT: Final = 200
_MAX_DOCUMENT_SEGMENTS: Final = 200
_MAX_RELATED_CONCEPTS: Final = 200
_MAX_STRUCTURED_RESPONSE_BYTES: Final = 4 * 1024 * 1024
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_IPC_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}$")


def _as_language(language: str) -> Language:
    normalized = language.strip().lower()
    if normalized not in _SUPPORTED_LANGUAGES:
        raise PMGSQueryError("INVALID_LANGUAGE", f"unsupported language: {language}")
    return cast(Language, normalized)


def _as_scheme(scheme: str) -> str:
    normalized = scheme.strip().lower()
    if normalized not in SUPPORTED_SCHEMES:
        raise PMGSQueryError("INVALID_SCHEME", f"unsupported scheme: {scheme}")
    return normalized


def _as_limit(limit: int) -> int:
    if not 1 <= limit <= _MAX_LIMIT:
        raise PMGSQueryError("INVALID_LIMIT", f"limit must be between 1 and {_MAX_LIMIT}")
    return limit


def _as_relation_page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= _MAX_RELATION_LIMIT:
        raise PMGSQueryError(
            "INVALID_RELATION_LIMIT",
            f"relation_limit must be between 1 and {_MAX_RELATION_LIMIT}",
        )
    if offset < 0:
        raise PMGSQueryError("INVALID_RELATION_OFFSET", "relation_offset must be at least 0")
    return limit, offset


def _as_query(query: str) -> str:
    clean = " ".join(query.split())
    if not clean or len(clean) > 500 or _CONTROL_CHARACTER.search(clean):
        raise PMGSQueryError("INVALID_QUERY", "query must be 1 to 500 printable characters")
    return clean


def _as_code(code: str) -> str:
    clean = code.strip()
    if not clean or len(clean) > 128 or _CONTROL_CHARACTER.search(clean):
        raise PMGSQueryError("INVALID_CODE", "code must be 1 to 128 printable characters")
    return clean


def _as_ipc_version(version: str | None, scheme: str) -> str | None:
    if version is None:
        return None
    if scheme != "ipc":
        raise PMGSQueryError("INVALID_VERSION", "version is supported only for IPC classifications")
    normalized = version.strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if not _IPC_VERSION.fullmatch(normalized):
        raise PMGSQueryError("INVALID_VERSION", "IPC version must use YYYY.MM")
    return normalized


def _validated_content_types(content_types: Sequence[str] | None) -> list[ContentType]:
    requested = list(content_types or ("classification", "document"))
    if not requested or set(requested) - _SUPPORTED_CONTENT_TYPES:
        raise PMGSQueryError(
            "INVALID_CONTENT_TYPE",
            "content_types must contain classification and/or document",
        )
    return [item for item in ("classification", "document") if item in requested]


def _fts_expression(query: str) -> str:
    """Build a literal FTS5 AND expression without exposing FTS operators."""
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query.split())


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _uses_trigram(query: str) -> bool:
    return all(len(term) >= 3 for term in query.split())


def _literal_excerpt(text: str, query: str, limit: int = 240) -> str:
    first_term = query.split()[0]
    position = text.casefold().find(first_term.casefold())
    if position < 0:
        return text[:limit]
    start = max(0, position - limit // 3)
    end = min(len(text), start + limit)
    return f"{'… ' if start else ''}{text[start:end]}{' …' if end < len(text) else ''}"


def _bounded_structured_response(payload: JSONDict) -> JSONDict:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(serialized) > _MAX_STRUCTURED_RESPONSE_BYTES:
        raise PMGSQueryError(
            "RESPONSE_TOO_LARGE",
            f"structured response exceeds the {_MAX_STRUCTURED_RESPONSE_BYTES}-byte maximum",
        )
    return payload


def _edition_value(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


class PMGSStore:
    """A deterministic, read-only view over one canonical PMGS SQLite store."""

    def __init__(self, path: Path, search_tokenizer: str = "unknown") -> None:
        self.path = path
        self.search_tokenizer = search_tokenizer

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        data_dir: str | os.PathLike[str] | None = None,
    ) -> PMGSStore:
        """Open schema v2, failing closed with an upgrade code for schema v1."""
        target = resolve_database(path, data_dir=data_dir)
        resolved = target.path
        if not resolved.is_file():
            raise FileNotFoundError(f"PMGS Reference database not found: {resolved}")
        provisional = cls(resolved)
        with provisional._connect() as connection:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if application_id == APPLICATION_ID and user_version == 1:
                raise PMGSQueryError(
                    "DATABASE_SCHEMA_UPGRADE_REQUIRED",
                    "schema v1 database is not supported; rebuild it with `pmgs setup SOURCE`",
                )
            if application_id != APPLICATION_ID or user_version != DATABASE_USER_VERSION:
                raise ValueError("not a supported PMGS Reference database")
            row = connection.execute(
                "SELECT schema_version, release_id, source_manifest_sha256 FROM release LIMIT 1"
            ).fetchone()
            fts_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'concept_text_fts'"
            ).fetchone()
        if row is None or row[0] != SCHEMA_VERSION:
            raise ValueError("not a supported PMGS Reference database")
        if target.pointer is not None and (
            row[1] != target.pointer.release_id
            or row[2] != target.pointer.source_manifest_sha256
            or user_version != target.pointer.database_schema_version
        ):
            raise ValueError("managed current.json identity does not match its database")
        if fts_row is None:
            raise ValueError("PMGS Reference search index is missing")
        fts_sql = str(fts_row[0]).lower()
        tokenizer = "trigram" if "tokenize = 'trigram'" in fts_sql else "legacy"
        return cls(resolved, tokenizer)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def __enter__(self) -> PMGSStore:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @staticmethod
    def _resolve_release(connection: sqlite3.Connection, release: str) -> sqlite3.Row:
        requested = release.strip()
        if requested == "current":
            row = connection.execute(
                "SELECT * FROM release ORDER BY release_id DESC LIMIT 1"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM release WHERE release_id = ?", (requested,)
            ).fetchone()
        if row is None:
            raise ReleaseNotFoundError(release)
        return cast(sqlite3.Row, row)

    @staticmethod
    def _resolve_edition(
        connection: sqlite3.Connection,
        release_id: str,
        scheme: str,
        edition: str | None,
    ) -> str:
        if scheme != "ipc":
            if edition not in (None, ""):
                raise PMGSQueryError(
                    "INVALID_EDITION", "edition is supported only for IPC classifications"
                )
            return ""
        if edition is not None:
            requested = edition.strip().upper()
            row = connection.execute(
                "SELECT 1 FROM concept WHERE release_id = ? AND scheme = 'ipc' "
                "AND edition = ? LIMIT 1",
                (release_id, requested),
            ).fetchone()
            if row is None:
                raise EditionNotFoundError(requested)
            return requested
        available = {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT edition FROM concept WHERE release_id = ? AND scheme = 'ipc'",
                (release_id,),
            ).fetchall()
        }
        for candidate in _IPC_EDITION_PRIORITY:
            if candidate in available:
                return candidate
        if not available:
            raise EditionNotFoundError("current")
        return sorted(available)[-1]

    @staticmethod
    def _release_source(connection: sqlite3.Connection, release_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT rs.owner, rs.original_url, rs.attribution, rs.source_locator, "
            "sf.source_id AS lineage_source_id FROM release_source rs "
            "JOIN source_file sf ON sf.file_id = rs.source_file_id WHERE rs.release_id = ?",
            (release_id,),
        ).fetchone()
        if row is None:
            raise ValueError("PMGS release source metadata is missing")
        return cast(sqlite3.Row, row)

    @classmethod
    def _source_payload(cls, row: sqlite3.Row) -> JSONDict:
        relative_path = str(row["relative_path"]).replace("\\", "/")
        return {
            "source_id": str(row["source_id"]),
            "title": PurePosixPath(relative_path).name,
            "relative_id": relative_path,
            "owner": str(row["owner"]),
            "original_url": str(row["original_url"]),
            "sha256": str(row["sha256"]).upper(),
            "attribution": str(row["attribution"]),
        }

    @classmethod
    def _sources(
        cls, connection: sqlite3.Connection, release_id: str, source_ids: Iterable[int]
    ) -> list[JSONValue]:
        identifiers = sorted(set(source_ids))
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = connection.execute(
            "SELECT sf.file_id, sf.source_id, sf.relative_path, sf.sha256, "
            "rs.owner, rs.original_url, rs.attribution FROM source_file sf "
            "JOIN release_source rs ON rs.release_id = sf.release_id "
            f"WHERE sf.release_id = ? AND sf.file_id IN ({placeholders}) ORDER BY sf.relative_path",
            (release_id, *identifiers),
        ).fetchall()
        return [cls._source_payload(row) for row in rows]

    @staticmethod
    def _concept_row(
        connection: sqlite3.Connection,
        release_id: str,
        scheme: str,
        edition: str,
        normalized_code: str,
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT * FROM concept WHERE release_id = ? AND scheme = ? AND edition = ? "
                "AND normalized_code = ?",
                (release_id, scheme, edition, normalized_code),
            ).fetchone(),
        )

    @staticmethod
    def _available_revisions(connection: sqlite3.Connection, concept_id: int) -> list[sqlite3.Row]:
        return cast(
            list[sqlite3.Row],
            connection.execute(
                "SELECT * FROM concept_revision WHERE concept_id = ? "
                "ORDER BY version_indicator, valid_from, revision_id",
                (concept_id,),
            ).fetchall(),
        )

    @staticmethod
    def _available_versions(revisions: Sequence[sqlite3.Row]) -> list[JSONValue]:
        return [
            {
                "version": str(row["version_indicator"]) or None,
                "valid_from": str(row["valid_from"]) if row["valid_from"] is not None else None,
                "valid_to": str(row["valid_to"]) if row["valid_to"] is not None else None,
            }
            for row in revisions
        ]

    @classmethod
    def _select_revision(
        cls,
        revisions: Sequence[sqlite3.Row],
        *,
        scheme: str,
        version: str | None,
        reference_date: str,
    ) -> tuple[sqlite3.Row | None, str | None]:
        if version is not None:
            return next(
                (row for row in revisions if str(row["version_indicator"]) == version), None
            ), "version_not_found"
        active = [
            row
            for row in revisions
            if (row["valid_from"] is None or str(row["valid_from"]) <= reference_date)
            and (row["valid_to"] is None or str(row["valid_to"]) >= reference_date)
        ]
        if len(active) > 1:
            raise PMGSQueryError(
                "MULTIPLE_ACTIVE_REVISIONS",
                "multiple classification revisions are active at the release reference date",
            )
        if active:
            return active[0], None
        if scheme == "ipc":
            return None, "not_valid_at_release"
        if len(revisions) == 1:
            return revisions[0], None
        return None, "not_valid_at_release"

    @staticmethod
    def _source_id(connection: sqlite3.Connection, file_id: int) -> str:
        row = connection.execute(
            "SELECT source_id FROM source_file WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row is None:
            raise ValueError("source lineage is missing")
        return str(row[0])

    @classmethod
    def _relation_rows(
        cls,
        connection: sqlite3.Connection,
        concept_id: int,
        revision_id: int | None,
        *,
        limit: int,
        offset: int,
    ) -> tuple[int, list[JSONDict], set[int]]:
        relation_candidates = """
            WITH relation_candidates AS (
                SELECT r.kind AS relation_type, target.scheme,
                    COALESCE(target.edition, '') AS edition,
                    target.normalized_code AS code, '' AS version,
                    r.source_file_id, r.source_locator
                FROM relation r
                JOIN concept target ON target.concept_id = r.to_concept_id
                WHERE r.from_concept_id = ?
                UNION ALL
                SELECT 'child', child.scheme, COALESCE(child.edition, ''),
                    child.normalized_code, '', r.source_file_id, r.source_locator
                FROM relation r
                JOIN concept child ON child.concept_id = r.from_concept_id
                WHERE r.to_concept_id = ? AND r.kind = 'parent'
                UNION ALL
                SELECT rr.kind, target.scheme, COALESCE(target.edition, ''),
                    target.normalized_code,
                    COALESCE(target_revision.version_indicator, ''),
                    rr.source_file_id, rr.source_locator
                FROM revision_relation rr
                JOIN concept_revision target_revision
                    ON target_revision.revision_id = rr.to_revision_id
                JOIN concept target ON target.concept_id = target_revision.concept_id
                WHERE rr.from_revision_id = ?
                UNION ALL
                SELECT CASE rr.kind
                        WHEN 'amended_to' THEN 'amended_from'
                        ELSE rr.kind
                    END,
                    source.scheme, COALESCE(source.edition, ''),
                    source.normalized_code,
                    COALESCE(source_revision.version_indicator, ''),
                    rr.source_file_id, rr.source_locator
                FROM revision_relation rr
                JOIN concept_revision source_revision
                    ON source_revision.revision_id = rr.from_revision_id
                JOIN concept source ON source.concept_id = source_revision.concept_id
                WHERE rr.to_revision_id = ?
            ),
            ranked_relations AS (
                SELECT relation_type, scheme, edition, code, version,
                    source_file_id, source_locator,
                    ROW_NUMBER() OVER (
                        PARTITION BY relation_type, scheme, edition, code, version
                        ORDER BY source_file_id, source_locator
                    ) AS lineage_rank
                FROM relation_candidates
            ),
            deduplicated_relations AS (
                SELECT relation_type, scheme, edition, code, version,
                    source_file_id, source_locator
                FROM ranked_relations
                WHERE lineage_rank = 1
            )
        """
        parameters = (concept_id, concept_id, revision_id, revision_id)
        count_row = connection.execute(
            f"{relation_candidates} SELECT COUNT(*) FROM deduplicated_relations", parameters
        ).fetchone()
        relation_count = int(count_row[0]) if count_row is not None else 0
        rows = connection.execute(
            f"""
            {relation_candidates}
            SELECT relations.relation_type, relations.scheme, relations.edition,
                relations.code, relations.version, relations.source_file_id,
                relations.source_locator, source.source_id
            FROM deduplicated_relations relations
            JOIN source_file source ON source.file_id = relations.source_file_id
            ORDER BY relations.relation_type, relations.scheme, relations.edition,
                relations.code, relations.version
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        payloads: list[JSONDict] = [
            {
                "type": str(row["relation_type"]),
                "scheme": str(row["scheme"]),
                "code": str(row["code"]),
                "edition": _edition_value(row["edition"]),
                "version": str(row["version"]) or None,
                "source_id": str(row["source_id"]),
                "locator": str(row["source_locator"]),
            }
            for row in rows
        ]
        source_file_ids = {int(row["source_file_id"]) for row in rows}
        return relation_count, payloads, source_file_ids

    @classmethod
    def _record(
        cls,
        connection: sqlite3.Connection,
        release_row: sqlite3.Row,
        concept: sqlite3.Row,
        revision: sqlite3.Row | None,
        *,
        language: Language,
        match_status: str,
        revisions: Sequence[sqlite3.Row],
        relation_limit: int,
        relation_offset: int,
    ) -> JSONDict:
        revision_id = int(revision["revision_id"]) if revision is not None else None
        text_rows: Sequence[sqlite3.Row] = ()
        property_rows: Sequence[sqlite3.Row] = ()
        linked_text_rows: Sequence[sqlite3.Row] = ()
        if revision_id is not None:
            text_rows = connection.execute(
                "SELECT kind, language, text, source_file_id, source_locator "
                "FROM concept_text WHERE revision_id = ? AND language = ? "
                "ORDER BY kind, sequence_number, text_id",
                (revision_id, language),
            ).fetchall()
            property_rows = connection.execute(
                "SELECT name, value, language, source_file_id, source_locator "
                "FROM concept_property WHERE revision_id = ? "
                "AND (language IS NULL OR language = ?) "
                "ORDER BY name, property_id",
                (revision_id, language),
            ).fetchall()
            linked_text_rows = connection.execute(
                "SELECT d.kind, d.language, dt.text, d.source_file_id, dt.source_locator "
                "FROM (SELECT document_id, source_locator FROM document_link "
                "WHERE concept_id = ? UNION ALL "
                "SELECT document_id, source_locator FROM document_revision_link "
                "WHERE revision_id = ?) links "
                "JOIN document d ON d.document_id = links.document_id "
                "JOIN document_text dt ON dt.document_id = d.document_id "
                "AND dt.source_locator = links.source_locator "
                "WHERE d.language IN (?, 'und') "
                "ORDER BY d.kind, d.document_id, dt.sequence_number",
                (int(concept["concept_id"]), revision_id, language),
            ).fetchall()
        document_rows = connection.execute(
            "SELECT d.document_id, d.kind, d.language, d.title, d.page_count, links.link_type, "
            "links.source_file_id, links.source_locator, "
            "d.source_file_id AS document_source_file_id "
            "FROM (SELECT document_id, kind AS link_type, source_file_id, source_locator "
            "FROM document_link WHERE concept_id = ? UNION ALL "
            "SELECT document_id, kind, source_file_id, source_locator FROM document_revision_link "
            "WHERE revision_id = ?) links JOIN document d ON d.document_id = links.document_id "
            "ORDER BY d.kind, d.document_id, links.link_type",
            (int(concept["concept_id"]), revision_id if revision_id is not None else -1),
        ).fetchall()
        labels: list[JSONValue] = []
        texts: list[JSONValue] = []
        for row in text_rows:
            payload: JSONDict = {
                "kind": str(row["kind"]),
                "language": str(row["language"]),
                "text": str(row["text"]),
                "provenance": "official",
                "source_id": cls._source_id(connection, int(row["source_file_id"])),
                "locator": str(row["source_locator"]),
            }
            (labels if row["kind"] == "label" else texts).append(payload)
        for row in linked_text_rows:
            texts.append(
                {
                    "kind": str(row["kind"]),
                    "language": str(row["language"]),
                    "text": str(row["text"]),
                    "provenance": "official",
                    "source_id": cls._source_id(connection, int(row["source_file_id"])),
                    "locator": str(row["source_locator"]),
                }
            )
        properties: list[JSONValue] = [
            {
                "name": str(row["name"]),
                "value": str(row["value"]),
                "language": str(row["language"]) if row["language"] is not None else None,
                "provenance": "official",
                "source_id": cls._source_id(connection, int(row["source_file_id"])),
                "locator": str(row["source_locator"]),
            }
            for row in property_rows
        ]
        relation_count, relations, relation_source_file_ids = cls._relation_rows(
            connection,
            int(concept["concept_id"]),
            revision_id,
            limit=relation_limit,
            offset=relation_offset,
        )
        documents: list[JSONValue] = []
        seen_documents: set[tuple[str, str]] = set()
        for row in document_rows:
            key = (str(row["document_id"]), str(row["link_type"]))
            if key in seen_documents:
                continue
            seen_documents.add(key)
            documents.append(
                {
                    "document_id": key[0],
                    "kind": str(row["kind"]),
                    "language": str(row["language"]),
                    "title": str(row["title"]),
                    "page_count": int(row["page_count"]) if row["page_count"] is not None else None,
                    "link_type": key[1],
                    "source_id": cls._source_id(connection, int(row["source_file_id"])),
                    "locator": str(row["source_locator"]),
                }
            )
        source_file_ids = {int(concept["source_file_id"])}
        if revision is not None:
            source_file_ids.add(int(revision["source_file_id"]))
        for rows in (text_rows, linked_text_rows, property_rows, document_rows):
            source_file_ids.update(int(item["source_file_id"]) for item in rows)
        source_file_ids.update(int(item["document_source_file_id"]) for item in document_rows)
        source_file_ids.update(relation_source_file_ids)
        next_offset = relation_offset + len(relations)
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": str(release_row["release_id"]),
            "reference_date": str(release_row["reference_date"]),
            "scheme": str(concept["scheme"]),
            "edition": _edition_value(concept["edition"]),
            "code": str(concept["normalized_code"]),
            "normalized_code": str(concept["normalized_code"]),
            "record_status": str(concept["record_status"]),
            "match_status": match_status,
            "version": (
                str(revision["version_indicator"]) or None if revision is not None else None
            ),
            "valid_from": str(revision["valid_from"])
            if revision is not None and revision["valid_from"] is not None
            else None,
            "valid_to": str(revision["valid_to"])
            if revision is not None and revision["valid_to"] is not None
            else None,
            "available_versions": cls._available_versions(revisions),
            "labels": labels,
            "texts": texts,
            "properties": properties,
            "relation_count": relation_count,
            "relation_offset": relation_offset,
            "relation_limit": relation_limit,
            "relations_truncated": len(relations) < relation_count,
            "next_relation_offset": next_offset if next_offset < relation_count else None,
            "relations": cast(list[JSONValue], relations),
            "documents": documents,
            "sources": cls._sources(connection, str(release_row["release_id"]), source_file_ids),
            "canonical_url": None,
        }

    @classmethod
    def _empty_record(
        cls,
        release_row: sqlite3.Row,
        scheme: str,
        edition: str,
        normalized_code: str,
        *,
        match_status: str,
        record_status: str | None = None,
        revisions: Sequence[sqlite3.Row] = (),
        sources: Sequence[JSONValue] = (),
        relation_limit: int = _DEFAULT_RELATION_LIMIT,
        relation_offset: int = 0,
    ) -> JSONDict:
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": str(release_row["release_id"]),
            "reference_date": str(release_row["reference_date"]),
            "scheme": scheme,
            "edition": _edition_value(edition),
            "code": normalized_code,
            "normalized_code": normalized_code,
            "record_status": record_status,
            "match_status": match_status,
            "version": None,
            "valid_from": None,
            "valid_to": None,
            "available_versions": cls._available_versions(revisions),
            "labels": [],
            "texts": [],
            "properties": [],
            "relation_count": 0,
            "relation_offset": relation_offset,
            "relation_limit": relation_limit,
            "relations_truncated": False,
            "next_relation_offset": None,
            "relations": [],
            "documents": [],
            "sources": list(sources),
            "canonical_url": None,
        }

    def lookup(
        self,
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
        language: str = "ja",
        *,
        version: str | None = None,
        relation_limit: int = _DEFAULT_RELATION_LIMIT,
        relation_offset: int = 0,
    ) -> JSONDict:
        """Return one exact record, selecting IPC revisions without guessing."""
        valid_scheme = _as_scheme(scheme)
        valid_code = _as_code(code)
        valid_language = _as_language(language)
        valid_version = _as_ipc_version(version, valid_scheme)
        valid_relation_limit, valid_relation_offset = _as_relation_page(
            relation_limit, relation_offset
        )
        normalized = normalize_code(valid_scheme, valid_code)
        with self._connect() as connection:
            release_row = self._resolve_release(connection, release)
            release_id = str(release_row["release_id"])
            resolved_edition = self._resolve_edition(connection, release_id, valid_scheme, edition)
            concept = self._concept_row(
                connection, release_id, valid_scheme, resolved_edition, normalized
            )
            if concept is None:
                return _bounded_structured_response(
                    self._empty_record(
                        release_row,
                        valid_scheme,
                        resolved_edition,
                        normalized,
                        match_status="not_found",
                        relation_limit=valid_relation_limit,
                        relation_offset=valid_relation_offset,
                    )
                )
            revisions = self._available_revisions(connection, int(concept["concept_id"]))
            revision, missing_status = self._select_revision(
                revisions,
                scheme=valid_scheme,
                version=valid_version,
                reference_date=str(release_row["reference_date"]),
            )
            if revision is None:
                return _bounded_structured_response(
                    self._empty_record(
                        release_row,
                        valid_scheme,
                        resolved_edition,
                        normalized,
                        match_status=cast(str, missing_status),
                        record_status=str(concept["record_status"]),
                        revisions=revisions,
                        sources=self._sources(
                            connection,
                            release_id,
                            {int(concept["source_file_id"])},
                        ),
                        relation_limit=valid_relation_limit,
                        relation_offset=valid_relation_offset,
                    )
                )
            match_status = "exact" if valid_code == normalized else "normalized_exact"
            return _bounded_structured_response(
                self._record(
                    connection,
                    release_row,
                    concept,
                    revision,
                    language=valid_language,
                    match_status=match_status,
                    revisions=revisions,
                    relation_limit=valid_relation_limit,
                    relation_offset=valid_relation_offset,
                )
            )

    @staticmethod
    def _validated_schemes(schemes: Sequence[str] | None) -> list[str]:
        if schemes is None:
            return ["fi", "fterm", "ipc"]
        if not schemes:
            raise PMGSQueryError("INVALID_SCHEME", "at least one scheme is required")
        return sorted({_as_scheme(scheme) for scheme in schemes})

    def search(
        self,
        query: str,
        schemes: Sequence[str] | None = None,
        release: str = "current",
        language: str = "ja",
        limit: int = 20,
    ) -> JSONDict:
        """Search only canonical classifications active at the release reference date."""
        valid_query = _as_query(query)
        valid_schemes = self._validated_schemes(schemes)
        valid_language = _as_language(language)
        valid_limit = _as_limit(limit)
        placeholders = ",".join("?" for _ in valid_schemes)
        with self._connect() as connection:
            release_row = self._resolve_release(connection, release)
            release_id = str(release_row["release_id"])
            reference_date = str(release_row["reference_date"])
            common = (
                "JOIN concept_revision cr ON cr.revision_id = ct.revision_id "
                "JOIN concept c ON c.concept_id = cr.concept_id "
                "JOIN source_file sf ON sf.file_id = ct.source_file_id "
            )
            active = (
                "c.record_status = 'canonical' AND (cr.valid_from IS NULL OR cr.valid_from <= ?) "
                "AND (cr.valid_to IS NULL OR cr.valid_to >= ?) "
            )
            if self.search_tokenizer == "trigram" and _uses_trigram(valid_query):
                rows = connection.execute(
                    "SELECT c.scheme, c.edition, c.normalized_code, cr.version_indicator, ct.kind, "
                    "snippet(concept_text_fts, 0, '', '', ' … ', 24) AS excerpt, "
                    "bm25(concept_text_fts) AS rank, sf.source_id FROM concept_text_fts "
                    "JOIN concept_text ct ON ct.text_id = concept_text_fts.rowid "
                    + common
                    + "WHERE concept_text_fts MATCH ? AND c.release_id = ? AND "
                    + active
                    + f"AND c.scheme IN ({placeholders}) AND ct.language = ? "
                    "ORDER BY rank, c.scheme, c.edition DESC, c.normalized_code, "
                    "cr.version_indicator, ct.kind LIMIT ?",
                    (
                        _fts_expression(valid_query),
                        release_id,
                        reference_date,
                        reference_date,
                        *valid_schemes,
                        valid_language,
                        valid_limit * 5,
                    ),
                ).fetchall()
                search_mode = "sqlite_fts5_trigram_lexical"
            else:
                terms = valid_query.split()
                like_conditions = " AND ".join("ct.text LIKE ? ESCAPE '\\'" for _ in terms)
                rows = connection.execute(
                    "SELECT c.scheme, c.edition, c.normalized_code, cr.version_indicator, ct.kind, "
                    "ct.text AS excerpt, 0.0 AS rank, sf.source_id FROM concept_text ct "
                    + common
                    + f"WHERE {like_conditions} AND c.release_id = ? AND "
                    + active
                    + f"AND c.scheme IN ({placeholders}) AND ct.language = ? "
                    "ORDER BY c.scheme, c.edition DESC, c.normalized_code, "
                    "cr.version_indicator, ct.kind LIMIT ?",
                    (
                        *(_like_pattern(term) for term in terms),
                        release_id,
                        reference_date,
                        reference_date,
                        *valid_schemes,
                        valid_language,
                        valid_limit * 5,
                    ),
                ).fetchall()
                search_mode = "sqlite_literal_substring_lexical"
        results: list[JSONValue] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            identity = (
                str(row["scheme"]),
                str(row["edition"]),
                str(row["normalized_code"]),
                str(row["version_indicator"]),
            )
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                {
                    "content_type": "classification",
                    "scheme": identity[0],
                    "edition": _edition_value(identity[1]),
                    "code": identity[2],
                    "version": identity[3] or None,
                    "kind": str(row["kind"]),
                    "excerpt": str(row["excerpt"])
                    if search_mode.endswith("trigram_lexical")
                    else _literal_excerpt(str(row["excerpt"]), valid_query),
                    "source_id": str(row["source_id"]),
                    "rank": float(row["rank"]),
                }
            )
            if len(results) == valid_limit:
                break
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "reference_date": reference_date,
            "query": valid_query,
            "search_mode": search_mode,
            "language": valid_language,
            "schemes": list(valid_schemes),
            "count": len(results),
            "results": results,
        }

    def search_pmgs(
        self,
        query: str,
        schemes: Sequence[str] | None = None,
        content_types: Sequence[str] | None = None,
        release: str = "current",
        language: str = "ja",
        limit: int = 20,
    ) -> JSONDict:
        """Search classifications and documents, applying the limit independently to each."""
        requested = _validated_content_types(content_types)
        classification = (
            self.search(query, schemes, release, language, limit)
            if "classification" in requested
            else None
        )
        document = (
            self.search_documents(query, release, language, limit)
            if "document" in requested
            else None
        )
        anchor = classification or document
        assert anchor is not None
        flat_results: list[JSONValue] = []
        search_modes: set[str] = set()
        for payload in (classification, document):
            if payload is not None:
                flat_results.extend(cast(list[JSONValue], payload["results"]))
                search_modes.add(str(payload["search_mode"]))

        def group(payload: JSONDict | None) -> JSONDict:
            return {
                "requested": payload is not None,
                "count": cast(int, payload["count"]) if payload is not None else 0,
                "search_mode": str(payload["search_mode"]) if payload is not None else None,
                "results": cast(list[JSONValue], payload["results"]) if payload is not None else [],
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": anchor["release_id"],
            "reference_date": anchor.get("reference_date"),
            "query": anchor["query"],
            "language": anchor["language"],
            "content_types": list(requested),
            "search_mode": (
                next(iter(search_modes)) if len(search_modes) == 1 else "mixed_lexical"
            ),
            "count": len(flat_results),
            "results": flat_results,
            "results_by_type": {
                "classification": group(classification),
                "document": group(document),
            },
        }

    def _hierarchy(
        self,
        direction: Literal["parents", "children"],
        scheme: str,
        code: str,
        release: str,
        edition: str | None,
    ) -> list[JSONDict]:
        desired = "parent" if direction == "parents" else "child"
        output: list[JSONDict] = []
        relation_offset = 0
        while True:
            record = self.lookup(
                scheme,
                code,
                release,
                edition,
                relation_limit=_MAX_RELATION_LIMIT,
                relation_offset=relation_offset,
            )
            relations = cast(list[JSONValue], record["relations"])
            for item in relations:
                if isinstance(item, dict) and item.get("type") == desired:
                    output.append(
                        self.lookup(
                            str(item["scheme"]),
                            str(item["code"]),
                            release,
                            cast(str | None, item.get("edition")),
                        )
                    )
            next_offset = record["next_relation_offset"]
            if next_offset is None:
                break
            relation_offset = int(cast(int, next_offset))
        return output

    def parents(
        self, scheme: str, code: str, release: str = "current", edition: str | None = None
    ) -> list[JSONDict]:
        return self._hierarchy("parents", scheme, code, release, edition)

    def children(
        self, scheme: str, code: str, release: str = "current", edition: str | None = None
    ) -> list[JSONDict]:
        return self._hierarchy("children", scheme, code, release, edition)

    def related_documents(
        self, scheme: str, code: str, release: str = "current", edition: str | None = None
    ) -> list[JSONDict]:
        record = self.lookup(scheme, code, release, edition)
        return [cast(JSONDict, item) for item in cast(list[JSONValue], record["documents"])]

    @classmethod
    def _document_summary(cls, row: sqlite3.Row) -> JSONDict:
        return {
            "document_id": str(row["document_id"]),
            "release_id": str(row["release_id"]),
            "kind": str(row["kind"]),
            "language": str(row["language"]),
            "title": str(row["title"]),
            "page_count": int(row["page_count"]) if row["page_count"] is not None else None,
            "link_kind": str(row["link_kind"]) if "link_kind" in row else None,
            "source": cls._source_payload(row),
        }

    def get_document(
        self,
        document_id: str,
        page: int | None = None,
        section: int | None = None,
        *,
        locator: str | None = None,
        segment_limit: int = _MAX_DOCUMENT_SEGMENTS,
        segment_offset: int = 0,
        related_classification_limit: int = _MAX_RELATED_CONCEPTS,
        related_classification_offset: int = 0,
    ) -> JSONDict:
        clean_id = document_id.strip()
        if not clean_id or len(clean_id) > 128 or _CONTROL_CHARACTER.search(clean_id):
            raise PMGSQueryError("INVALID_DOCUMENT_ID", "invalid PMGS document identifier")
        if sum(value is not None for value in (page, section, locator)) > 1:
            raise PMGSQueryError(
                "INVALID_DOCUMENT_SELECTOR",
                "page, section, and locator are mutually exclusive",
            )
        if page is not None and page < 1:
            raise PMGSQueryError("INVALID_PAGE", "page must be at least 1")
        if section is not None and section < 1:
            raise PMGSQueryError("INVALID_SECTION", "section must be at least 1")
        clean_locator = locator.strip() if locator is not None else None
        if clean_locator == "":
            raise PMGSQueryError("INVALID_LOCATOR", "locator must not be empty")
        if clean_locator is not None and (
            len(clean_locator) > 256 or _CONTROL_CHARACTER.search(clean_locator)
        ):
            raise PMGSQueryError("INVALID_LOCATOR", "locator must be 1 to 256 printable characters")
        if not 1 <= segment_limit <= _MAX_DOCUMENT_SEGMENTS:
            raise PMGSQueryError(
                "INVALID_SEGMENT_LIMIT",
                f"segment_limit must be between 1 and {_MAX_DOCUMENT_SEGMENTS}",
            )
        if segment_offset < 0:
            raise PMGSQueryError("INVALID_SEGMENT_OFFSET", "segment_offset must be at least 0")
        if not 1 <= related_classification_limit <= _MAX_RELATED_CONCEPTS:
            raise PMGSQueryError(
                "INVALID_RELATED_CLASSIFICATION_LIMIT",
                f"related_classification_limit must be between 1 and {_MAX_RELATED_CONCEPTS}",
            )
        if related_classification_offset < 0:
            raise PMGSQueryError(
                "INVALID_RELATED_CLASSIFICATION_OFFSET",
                "related_classification_offset must be at least 0",
            )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.*, sf.source_id, sf.relative_path, sf.sha256, "
                "rs.owner, rs.original_url, rs.attribution "
                "FROM document d JOIN source_file sf ON sf.file_id = d.source_file_id "
                "JOIN release_source rs ON rs.release_id = d.release_id WHERE d.document_id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(clean_id)
            filters = ["document_id = ?"]
            parameters: list[object] = [clean_id]
            if page is not None:
                filters.append("(locator = ? OR source_locator = ?)")
                parameters.extend((f"page:{page}", f"page:{page}"))
            elif section is not None:
                filters.append("sequence_number = ?")
                parameters.append(section)
            elif clean_locator is not None:
                filters.append("(locator = ? OR heading = ? OR source_locator = ?)")
                parameters.extend((clean_locator, clean_locator, clean_locator))
            where = " AND ".join(filters)
            count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM document_text WHERE {where}", parameters
                ).fetchone()[0]
            )
            if any(value is not None for value in (page, section, clean_locator)) and count == 0:
                raise PMGSQueryError(
                    "DOCUMENT_SELECTOR_NOT_FOUND",
                    "document selector did not match any segment",
                )
            segments = connection.execute(
                "SELECT sequence_number, locator, heading, text, source_locator "
                f"FROM document_text WHERE {where} "
                "ORDER BY sequence_number LIMIT ? OFFSET ?",
                (*parameters, segment_limit, segment_offset),
            ).fetchall()
            related_rows = connection.execute(
                "SELECT c.scheme, c.edition, c.normalized_code, "
                "links.version_indicator, links.kind "
                "FROM (SELECT concept_id, NULL AS revision_id, NULL AS version_indicator, kind "
                "FROM document_link WHERE document_id = ? UNION ALL "
                "SELECT cr.concept_id, drl.revision_id, cr.version_indicator, drl.kind "
                "FROM document_revision_link drl JOIN concept_revision cr "
                "ON cr.revision_id = drl.revision_id "
                "WHERE drl.document_id = ?) links "
                "JOIN concept c ON c.concept_id = links.concept_id "
                "ORDER BY c.scheme, c.edition, c.normalized_code, "
                "links.version_indicator, links.kind LIMIT ? OFFSET ?",
                (
                    clean_id,
                    clean_id,
                    related_classification_limit,
                    related_classification_offset,
                ),
            ).fetchall()
            related_count = int(
                connection.execute(
                    "SELECT (SELECT COUNT(*) FROM document_link WHERE document_id = ?) + "
                    "(SELECT COUNT(*) FROM document_revision_link WHERE document_id = ?)",
                    (clean_id, clean_id),
                ).fetchone()[0]
            )
        next_segment_offset = segment_offset + len(segments)
        next_related_offset = related_classification_offset + len(related_rows)
        return _bounded_structured_response(
            {
                "schema_version": SCHEMA_VERSION,
                **self._document_summary(cast(sqlite3.Row, row)),
                "metadata": cast(JSONValue, json.loads(str(row["metadata_json"]))),
                "selector": {
                    "page": page,
                    "section": section,
                    "locator": clean_locator,
                },
                "segment_count": count,
                "segment_limit": segment_limit,
                "segment_offset": segment_offset,
                "segments_truncated": next_segment_offset < count,
                "next_segment_offset": (
                    next_segment_offset if next_segment_offset < count else None
                ),
                "segments": [
                    {
                        "sequence_number": int(item["sequence_number"]),
                        "locator": str(item["locator"]),
                        "heading": str(item["heading"]) if item["heading"] is not None else None,
                        "text": str(item["text"]),
                        "source_locator": str(item["source_locator"]),
                    }
                    for item in segments
                ],
                "related_classification_count": related_count,
                "related_classification_limit": related_classification_limit,
                "related_classification_offset": related_classification_offset,
                "related_classifications_truncated": next_related_offset < related_count,
                "next_related_classification_offset": (
                    next_related_offset if next_related_offset < related_count else None
                ),
                "related_classifications": [
                    {
                        "scheme": str(item["scheme"]),
                        "edition": _edition_value(item["edition"]),
                        "code": str(item["normalized_code"]),
                        "version": str(item["version_indicator"])
                        if item["version_indicator"] is not None
                        else None,
                        "type": str(item["kind"]),
                    }
                    for item in related_rows
                ],
            }
        )

    def search_documents(
        self, query: str, release: str = "current", language: str = "ja", limit: int = 20
    ) -> JSONDict:
        valid_query = _as_query(query)
        valid_language = _as_language(language)
        valid_limit = _as_limit(limit)
        with self._connect() as connection:
            release_row = self._resolve_release(connection, release)
            release_id = str(release_row["release_id"])
            if self.search_tokenizer == "trigram" and _uses_trigram(valid_query):
                rows = connection.execute(
                    "SELECT d.document_id, d.kind, d.language, d.title, "
                    "dt.sequence_number, dt.locator, "
                    "snippet(document_text_fts, 0, '', '', ' … ', 24) AS excerpt, "
                    "bm25(document_text_fts) AS rank, sf.source_id FROM document_text_fts "
                    "JOIN document_text dt ON dt.document_text_id = document_text_fts.rowid "
                    "JOIN document d ON d.document_id = dt.document_id "
                    "JOIN source_file sf ON sf.file_id = d.source_file_id "
                    "WHERE document_text_fts MATCH ? AND d.release_id = ? "
                    "AND d.language IN (?, 'und') "
                    "ORDER BY rank, d.document_id, dt.sequence_number LIMIT ?",
                    (_fts_expression(valid_query), release_id, valid_language, valid_limit * 5),
                ).fetchall()
                search_mode = "sqlite_fts5_trigram_lexical"
            else:
                terms = valid_query.split()
                like_conditions = " AND ".join("dt.text LIKE ? ESCAPE '\\'" for _ in terms)
                rows = connection.execute(
                    "SELECT d.document_id, d.kind, d.language, d.title, "
                    "dt.sequence_number, dt.locator, "
                    "dt.text AS excerpt, 0.0 AS rank, sf.source_id FROM document_text dt "
                    "JOIN document d ON d.document_id = dt.document_id "
                    "JOIN source_file sf ON sf.file_id = d.source_file_id "
                    f"WHERE {like_conditions} AND d.release_id = ? AND d.language IN (?, 'und') "
                    "ORDER BY d.document_id, dt.sequence_number LIMIT ?",
                    (
                        *(_like_pattern(term) for term in terms),
                        release_id,
                        valid_language,
                        valid_limit * 5,
                    ),
                ).fetchall()
                search_mode = "sqlite_literal_substring_lexical"
        results: list[JSONValue] = []
        seen: set[str] = set()
        for row in rows:
            document_id = str(row["document_id"])
            if document_id in seen:
                continue
            seen.add(document_id)
            results.append(
                {
                    "content_type": "document",
                    "document_id": document_id,
                    "kind": str(row["kind"]),
                    "language": str(row["language"]),
                    "title": str(row["title"]),
                    "sequence_number": int(row["sequence_number"]),
                    "locator": str(row["locator"]),
                    "excerpt": str(row["excerpt"])
                    if search_mode.endswith("trigram_lexical")
                    else _literal_excerpt(str(row["excerpt"]), valid_query),
                    "source_id": str(row["source_id"]),
                    "rank": float(row["rank"]),
                }
            )
            if len(results) == valid_limit:
                break
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "reference_date": str(release_row["reference_date"]),
            "query": valid_query,
            "search_mode": search_mode,
            "language": valid_language,
            "count": len(results),
            "results": results,
        }

    def release_info(self, release: str = "current") -> JSONDict:
        with self._connect() as connection:
            row = self._resolve_release(connection, release)
            release_id = str(row["release_id"])
            source = self._release_source(connection, release_id)
            concept_rows = connection.execute(
                "SELECT scheme, edition, COUNT(*) AS count FROM concept WHERE release_id = ? "
                "GROUP BY scheme, edition ORDER BY scheme, edition",
                (release_id,),
            ).fetchall()
            document_rows = connection.execute(
                "SELECT kind, language, COUNT(*) AS count FROM document WHERE release_id = ? "
                "GROUP BY kind, language ORDER BY kind, language",
                (release_id,),
            ).fetchall()
        return {
            "schema_version": str(row["schema_version"]),
            "release_id": release_id,
            "reference_date": str(row["reference_date"]),
            "source_manifest_sha256": str(row["source_manifest_sha256"]).upper(),
            "source_file_count": int(row["source_file_count"]),
            "source_total_bytes": int(row["source_total_bytes"]),
            "source": {
                "owner": str(source["owner"]),
                "original_url": str(source["original_url"]),
                "attribution": str(source["attribution"]),
                "lineage": {
                    "source_id": str(source["lineage_source_id"]),
                    "locator": str(source["source_locator"]),
                },
            },
            "search_index": f"fts5_{self.search_tokenizer}",
            "concept_counts": [
                {
                    "scheme": str(item["scheme"]),
                    "edition": _edition_value(item["edition"]),
                    "count": int(item["count"]),
                }
                for item in concept_rows
            ],
            "document_counts": [
                {
                    "kind": str(item["kind"]),
                    "language": str(item["language"]),
                    "count": int(item["count"]),
                }
                for item in document_rows
            ],
        }
