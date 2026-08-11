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
from pmgs_reference.schema import APPLICATION_ID, SCHEMA_VERSION
from pmgs_reference.store_types import JSONDict as JSONDict
from pmgs_reference.store_types import JSONValue as JSONValue

Language = Literal["ja", "en"]

_SUPPORTED_LANGUAGES: Final = frozenset({"ja", "en"})
_IPC_EDITION_PRIORITY: Final = ("8U", "8B", "7", "7E", "6", "5", "4")
_MAX_LIMIT: Final = 100
_MAX_DOCUMENT_SEGMENTS: Final = 200
_MAX_RELATED_CONCEPTS: Final = 200
_SOURCE_OWNER: Final = "JPO"
_SOURCE_URL: Final = "https://www.jpo.go.jp/system/laws/sesaku/data/download.html"
_ATTRIBUTION: Final = "Copyright (C) JPO"
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


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
    prefix = "… " if start else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _edition_value(value: str) -> str | None:
    return value or None


class PMGSStore:
    """A deterministic, read-only view over one canonical PMGS SQLite store.

    Search methods use SQLite FTS5 trigram matching, with a literal substring
    fallback for terms shorter than three characters. They do not perform semantic
    search, AI inference, translation, or network access.
    """

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
        """Open a canonical store using explicit paths and managed current pointers."""
        target = resolve_database(path, data_dir=data_dir)
        resolved = target.path
        if not resolved.is_file():
            raise FileNotFoundError(f"PMGS Reference database not found: {resolved}")
        provisional = cls(resolved)
        with provisional._connect() as connection:
            application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            row = connection.execute(
                "SELECT schema_version, release_id, source_manifest_sha256 FROM release LIMIT 1"
            ).fetchone()
            fts_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'concept_text_fts'"
            ).fetchone()
        if application_id != APPLICATION_ID or row is None or row[0] != SCHEMA_VERSION:
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
    def _resolve_release(connection: sqlite3.Connection, release: str) -> str:
        requested = release.strip()
        if requested == "current":
            row = connection.execute(
                "SELECT release_id FROM release ORDER BY release_id DESC LIMIT 1"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT release_id FROM release WHERE release_id = ?", (requested,)
            ).fetchone()
        if row is None:
            raise ReleaseNotFoundError(release)
        return str(row[0])

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
        rows = connection.execute(
            "SELECT DISTINCT edition FROM concept WHERE release_id = ? AND scheme = 'ipc'",
            (release_id,),
        ).fetchall()
        available = {str(row[0]) for row in rows}
        for candidate in _IPC_EDITION_PRIORITY:
            if candidate in available:
                return candidate
        if not available:
            raise EditionNotFoundError("current")
        return sorted(available)[-1]

    @staticmethod
    def _source_payload(row: sqlite3.Row) -> JSONDict:
        relative_path = str(row["relative_path"]).replace("\\", "/")
        return {
            "source_id": str(row["source_id"]),
            "title": PurePosixPath(relative_path).name,
            "relative_id": relative_path,
            "owner": _SOURCE_OWNER,
            "original_url": _SOURCE_URL,
            "sha256": str(row["sha256"]).upper(),
            "attribution": _ATTRIBUTION,
        }

    @classmethod
    def _sources(cls, connection: sqlite3.Connection, source_ids: Iterable[int]) -> list[JSONValue]:
        identifiers = sorted(set(source_ids))
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = connection.execute(
            f"SELECT file_id, source_id, relative_path, sha256 FROM source_file "
            f"WHERE file_id IN ({placeholders}) ORDER BY relative_path",
            identifiers,
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

    @classmethod
    def _record_from_row(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        language: Language,
        match_status: str,
    ) -> JSONDict:
        concept_id = int(row["concept_id"])
        text_rows = connection.execute(
            "SELECT ct.kind, ct.language, ct.text, ct.source_file_id, ct.source_locator "
            "FROM concept_text ct WHERE ct.concept_id = ? AND ct.language = ? "
            "ORDER BY ct.kind, ct.sequence_number, ct.text_id",
            (concept_id, language),
        ).fetchall()
        linked_text_rows = connection.execute(
            "SELECT d.kind, d.language, dt.text, d.source_file_id, dt.source_locator "
            "FROM document_link dl JOIN document d ON d.document_id = dl.document_id "
            "JOIN document_text dt ON dt.document_id = d.document_id "
            "AND dt.source_locator = dl.source_locator "
            "WHERE dl.concept_id = ? AND d.language = ? "
            "ORDER BY d.kind, d.document_id, dt.sequence_number",
            (concept_id, language),
        ).fetchall()
        property_rows = connection.execute(
            "SELECT name, value, language, source_file_id, source_locator "
            "FROM concept_property WHERE concept_id = ? AND (language IS NULL OR language = ?) "
            "ORDER BY name, property_id",
            (concept_id, language),
        ).fetchall()
        relation_rows = connection.execute(
            "SELECT r.kind AS relation_kind, target.scheme, target.edition, "
            "target.normalized_code, r.source_file_id FROM relation r "
            "JOIN concept target ON target.concept_id = r.to_concept_id "
            "WHERE r.from_concept_id = ? UNION ALL "
            "SELECT 'child' AS relation_kind, child.scheme, child.edition, "
            "child.normalized_code, r.source_file_id FROM relation r "
            "JOIN concept child ON child.concept_id = r.from_concept_id "
            "WHERE r.to_concept_id = ? AND r.kind = 'parent' "
            "ORDER BY relation_kind, scheme, edition, normalized_code",
            (concept_id, concept_id),
        ).fetchall()
        document_rows = connection.execute(
            "SELECT d.document_id, d.kind, d.language, d.title, d.page_count, "
            "dl.kind AS link_type, dl.source_file_id, d.source_file_id AS document_source_file_id "
            "FROM document_link dl JOIN document d ON d.document_id = dl.document_id "
            "WHERE dl.concept_id = ? ORDER BY d.kind, d.document_id, dl.kind",
            (concept_id,),
        ).fetchall()
        labels: list[JSONValue] = []
        texts: list[JSONValue] = []
        for text_row in text_rows:
            payload: JSONDict = {
                "language": str(text_row["language"]),
                "text": str(text_row["text"]),
                "provenance": "official",
            }
            if text_row["kind"] == "label":
                labels.append(payload)
            else:
                texts.append(
                    {
                        "kind": str(text_row["kind"]),
                        **payload,
                        "source_id": cls._source_id(connection, int(text_row["source_file_id"])),
                        "locator": str(text_row["source_locator"]),
                    }
                )
        for text_row in linked_text_rows:
            texts.append(
                {
                    "kind": str(text_row["kind"]),
                    "language": str(text_row["language"]),
                    "text": str(text_row["text"]),
                    "provenance": "official",
                    "source_id": cls._source_id(connection, int(text_row["source_file_id"])),
                    "locator": str(text_row["source_locator"]),
                }
            )
        properties: list[JSONValue] = [
            {
                "name": str(property_row["name"]),
                "value": str(property_row["value"]),
                "language": (
                    str(property_row["language"]) if property_row["language"] is not None else None
                ),
                "provenance": "official",
                "source_id": cls._source_id(connection, int(property_row["source_file_id"])),
                "locator": str(property_row["source_locator"]),
            }
            for property_row in property_rows
        ]
        relations: list[JSONValue] = [
            {
                "type": str(relation_row["relation_kind"]),
                "scheme": str(relation_row["scheme"]),
                "code": str(relation_row["normalized_code"]),
                "edition": _edition_value(str(relation_row["edition"])),
            }
            for relation_row in relation_rows
        ]
        documents: list[JSONValue] = [
            {
                "document_id": str(document_row["document_id"]),
                "kind": str(document_row["kind"]),
                "language": str(document_row["language"]),
                "title": str(document_row["title"]),
                "page_count": (
                    int(document_row["page_count"])
                    if document_row["page_count"] is not None
                    else None
                ),
                "link_type": str(document_row["link_type"]),
            }
            for document_row in document_rows
        ]
        source_file_ids = {int(row["source_file_id"])}
        source_file_ids.update(int(item["source_file_id"]) for item in text_rows)
        source_file_ids.update(int(item["source_file_id"]) for item in linked_text_rows)
        source_file_ids.update(int(item["source_file_id"]) for item in property_rows)
        source_file_ids.update(int(item["source_file_id"]) for item in relation_rows)
        source_file_ids.update(int(item["source_file_id"]) for item in document_rows)
        source_file_ids.update(int(item["document_source_file_id"]) for item in document_rows)
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": str(row["release_id"]),
            "scheme": str(row["scheme"]),
            "edition": _edition_value(str(row["edition"])),
            "code": str(row["normalized_code"]),
            "normalized_code": str(row["normalized_code"]),
            "match_status": match_status,
            "labels": labels,
            "texts": texts,
            "properties": properties,
            "relations": relations,
            "documents": documents,
            "sources": cls._sources(connection, source_file_ids),
            "canonical_url": None,
        }

    @staticmethod
    def _source_id(connection: sqlite3.Connection, file_id: int) -> str:
        row = connection.execute(
            "SELECT source_id FROM source_file WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row is None:  # pragma: no cover - protected by foreign keys and validation
            raise ValueError("source lineage is missing")
        return str(row[0])

    @staticmethod
    def _not_found_record(
        release_id: str,
        scheme: str,
        edition: str,
        normalized_code: str,
    ) -> JSONDict:
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "scheme": scheme,
            "edition": _edition_value(edition),
            "code": normalized_code,
            "normalized_code": normalized_code,
            "match_status": "not_found",
            "labels": [],
            "texts": [],
            "properties": [],
            "relations": [],
            "documents": [],
            "sources": [],
            "canonical_url": None,
        }

    def lookup(
        self,
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
        language: str = "ja",
    ) -> JSONDict:
        """Return one exact or normalized-exact official classification record."""
        valid_scheme = _as_scheme(scheme)
        valid_code = _as_code(code)
        valid_language = _as_language(language)
        normalized = normalize_code(valid_scheme, valid_code)
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            resolved_edition = self._resolve_edition(connection, release_id, valid_scheme, edition)
            row = self._concept_row(
                connection, release_id, valid_scheme, resolved_edition, normalized
            )
            if row is None:
                return self._not_found_record(
                    release_id, valid_scheme, resolved_edition, normalized
                )
            match_status = "exact" if valid_code == normalized else "normalized_exact"
            return self._record_from_row(
                connection, row, language=valid_language, match_status=match_status
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
        """Search official text lexically with FTS5 trigram and a short-query fallback."""
        valid_query = _as_query(query)
        valid_schemes = self._validated_schemes(schemes)
        valid_language = _as_language(language)
        valid_limit = _as_limit(limit)
        placeholders = ",".join("?" for _ in valid_schemes)
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            if self.search_tokenizer == "trigram" and _uses_trigram(valid_query):
                rows = connection.execute(
                    "SELECT c.concept_id, c.scheme, c.edition, c.normalized_code, ct.kind, "
                    "snippet(concept_text_fts, 0, '', '', ' … ', 24) AS excerpt, "
                    "bm25(concept_text_fts) AS rank, sf.source_id "
                    "FROM concept_text_fts "
                    "JOIN concept_text ct ON ct.text_id = concept_text_fts.rowid "
                    "JOIN concept c ON c.concept_id = ct.concept_id "
                    "JOIN source_file sf ON sf.file_id = ct.source_file_id "
                    "WHERE concept_text_fts MATCH ? AND c.release_id = ? "
                    f"AND c.scheme IN ({placeholders}) AND ct.language = ? "
                    "ORDER BY rank, c.scheme, c.edition DESC, c.normalized_code, ct.kind "
                    "LIMIT ?",
                    (
                        _fts_expression(valid_query),
                        release_id,
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
                    "SELECT c.concept_id, c.scheme, c.edition, c.normalized_code, ct.kind, "
                    "ct.text AS excerpt, 0.0 AS rank, sf.source_id "
                    "FROM concept_text ct JOIN concept c ON c.concept_id = ct.concept_id "
                    "JOIN source_file sf ON sf.file_id = ct.source_file_id "
                    f"WHERE {like_conditions} AND c.release_id = ? "
                    f"AND c.scheme IN ({placeholders}) AND ct.language = ? "
                    "ORDER BY c.scheme, c.edition DESC, c.normalized_code, ct.kind LIMIT ?",
                    (
                        *(_like_pattern(term) for term in terms),
                        release_id,
                        *valid_schemes,
                        valid_language,
                        valid_limit * 5,
                    ),
                ).fetchall()
                search_mode = "sqlite_literal_substring_lexical"
        results: list[JSONValue] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            identity = (str(row["scheme"]), str(row["edition"]), str(row["normalized_code"]))
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                {
                    "content_type": "classification",
                    "scheme": identity[0],
                    "edition": _edition_value(identity[1]),
                    "code": identity[2],
                    "kind": str(row["kind"]),
                    "excerpt": (
                        str(row["excerpt"])
                        if search_mode == "sqlite_fts5_trigram_lexical"
                        else _literal_excerpt(str(row["excerpt"]), valid_query)
                    ),
                    "source_id": str(row["source_id"]),
                    "rank": float(row["rank"]),
                }
            )
            if len(results) == valid_limit:
                break
        scheme_values: list[JSONValue] = [item for item in valid_schemes]
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "query": valid_query,
            "search_mode": search_mode,
            "language": valid_language,
            "schemes": scheme_values,
            "count": len(results),
            "results": results,
        }

    def _hierarchy(
        self,
        direction: Literal["parents", "children"],
        scheme: str,
        code: str,
        release: str,
        edition: str | None,
    ) -> list[JSONDict]:
        valid_scheme = _as_scheme(scheme)
        normalized = normalize_code(valid_scheme, _as_code(code))
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            resolved_edition = self._resolve_edition(connection, release_id, valid_scheme, edition)
            row = self._concept_row(
                connection, release_id, valid_scheme, resolved_edition, normalized
            )
            if row is None:
                return []
            if direction == "parents":
                join_column = "r.to_concept_id"
                where_column = "r.from_concept_id"
            else:
                join_column = "r.from_concept_id"
                where_column = "r.to_concept_id"
            related_rows = connection.execute(
                f"SELECT related.* FROM relation r JOIN concept related "
                f"ON related.concept_id = {join_column} "
                f"WHERE {where_column} = ? AND r.kind = 'parent' "
                "ORDER BY related.sequence_number, related.normalized_code",
                (int(row["concept_id"]),),
            ).fetchall()
            return [
                self._record_from_row(connection, related, language="ja", match_status="exact")
                for related in related_rows
            ]

    def parents(
        self,
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
    ) -> list[JSONDict]:
        """Return immediate parents in deterministic order."""
        return self._hierarchy("parents", scheme, code, release, edition)

    def children(
        self,
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
    ) -> list[JSONDict]:
        """Return immediate children in deterministic order."""
        return self._hierarchy("children", scheme, code, release, edition)

    def related_documents(
        self,
        scheme: str,
        code: str,
        release: str = "current",
        edition: str | None = None,
    ) -> list[JSONDict]:
        """Return metadata for official documents linked to a classification."""
        valid_scheme = _as_scheme(scheme)
        normalized = normalize_code(valid_scheme, _as_code(code))
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            resolved_edition = self._resolve_edition(connection, release_id, valid_scheme, edition)
            concept = self._concept_row(
                connection, release_id, valid_scheme, resolved_edition, normalized
            )
            if concept is None:
                return []
            rows = connection.execute(
                "SELECT d.*, dl.kind AS link_kind, sf.source_id, sf.relative_path, sf.sha256 "
                "FROM document_link dl JOIN document d ON d.document_id = dl.document_id "
                "JOIN source_file sf ON sf.file_id = d.source_file_id "
                "WHERE dl.concept_id = ? ORDER BY d.kind, d.document_id",
                (int(concept["concept_id"]),),
            ).fetchall()
            return [self._document_summary(row) for row in rows]

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
        section: str | None = None,
    ) -> JSONDict:
        """Return official document text, bounded when no page or section is specified."""
        clean_id = document_id.strip()
        if not clean_id or len(clean_id) > 128 or _CONTROL_CHARACTER.search(clean_id):
            raise PMGSQueryError("INVALID_DOCUMENT_ID", "invalid PMGS document identifier")
        if page is not None and section is not None:
            raise PMGSQueryError(
                "INVALID_DOCUMENT_SELECTOR", "page and section are mutually exclusive"
            )
        if page is not None and page < 1:
            raise PMGSQueryError("INVALID_PAGE", "page must be at least 1")
        clean_section = section.strip() if section is not None else None
        if clean_section == "":
            raise PMGSQueryError("INVALID_SECTION", "section must not be empty")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT d.*, sf.source_id, sf.relative_path, sf.sha256 "
                "FROM document d JOIN source_file sf ON sf.file_id = d.source_file_id "
                "WHERE d.document_id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(clean_id)
            filters = ["document_id = ?"]
            parameters: list[object] = [clean_id]
            if page is not None:
                filters.append("locator = ?")
                parameters.append(f"page:{page}")
            elif clean_section is not None:
                filters.append("(locator = ? OR heading = ?)")
                parameters.extend((clean_section, clean_section))
            where = " AND ".join(filters)
            count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM document_text WHERE {where}",
                    parameters,
                ).fetchone()[0]
            )
            segments = connection.execute(
                f"SELECT sequence_number, locator, heading, text, source_locator "
                f"FROM document_text WHERE {where} "
                "ORDER BY sequence_number LIMIT ?",
                (*parameters, _MAX_DOCUMENT_SEGMENTS),
            ).fetchall()
            related_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM document_link WHERE document_id = ?", (clean_id,)
                ).fetchone()[0]
            )
            related = connection.execute(
                "SELECT c.scheme, c.edition, c.normalized_code, dl.kind "
                "FROM document_link dl JOIN concept c ON c.concept_id = dl.concept_id "
                "WHERE dl.document_id = ? ORDER BY c.scheme, c.edition, c.normalized_code LIMIT ?",
                (clean_id, _MAX_RELATED_CONCEPTS),
            ).fetchall()
        return {
            "schema_version": SCHEMA_VERSION,
            **self._document_summary(row),
            "metadata": cast(JSONValue, json.loads(str(row["metadata_json"]))),
            "selector": {"page": page, "section": clean_section},
            "segment_count": count,
            "segments_truncated": count > len(segments),
            "segments": [
                {
                    "sequence_number": int(segment["sequence_number"]),
                    "locator": str(segment["locator"]),
                    "heading": (
                        str(segment["heading"]) if segment["heading"] is not None else None
                    ),
                    "text": str(segment["text"]),
                    "source_locator": str(segment["source_locator"]),
                }
                for segment in segments
            ],
            "related_classification_count": related_count,
            "related_classifications_truncated": related_count > len(related),
            "related_classifications": [
                {
                    "scheme": str(item["scheme"]),
                    "edition": _edition_value(str(item["edition"])),
                    "code": str(item["normalized_code"]),
                    "type": str(item["kind"]),
                }
                for item in related
            ],
        }

    def search_documents(
        self,
        query: str,
        release: str = "current",
        language: str = "ja",
        limit: int = 20,
    ) -> JSONDict:
        """Search official documents lexically with FTS5 and a short-query fallback."""
        valid_query = _as_query(query)
        valid_language = _as_language(language)
        valid_limit = _as_limit(limit)
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            if self.search_tokenizer == "trigram" and _uses_trigram(valid_query):
                rows = connection.execute(
                    "SELECT d.document_id, d.kind, d.language, d.title, dt.sequence_number, "
                    "dt.locator, snippet(document_text_fts, 0, '', '', ' … ', 24) AS excerpt, "
                    "bm25(document_text_fts) AS rank, sf.source_id "
                    "FROM document_text_fts "
                    "JOIN document_text dt ON dt.document_text_id = document_text_fts.rowid "
                    "JOIN document d ON d.document_id = dt.document_id "
                    "JOIN source_file sf ON sf.file_id = d.source_file_id "
                    "WHERE document_text_fts MATCH ? AND d.release_id = ? "
                    "AND d.language IN (?, 'und') "
                    "ORDER BY rank, d.document_id, dt.sequence_number LIMIT ?",
                    (
                        _fts_expression(valid_query),
                        release_id,
                        valid_language,
                        valid_limit * 5,
                    ),
                ).fetchall()
                search_mode = "sqlite_fts5_trigram_lexical"
            else:
                terms = valid_query.split()
                like_conditions = " AND ".join("dt.text LIKE ? ESCAPE '\\'" for _ in terms)
                rows = connection.execute(
                    "SELECT d.document_id, d.kind, d.language, d.title, dt.sequence_number, "
                    "dt.locator, dt.text AS excerpt, 0.0 AS rank, sf.source_id "
                    "FROM document_text dt JOIN document d ON d.document_id = dt.document_id "
                    "JOIN source_file sf ON sf.file_id = d.source_file_id "
                    f"WHERE {like_conditions} AND d.release_id = ? "
                    "AND d.language IN (?, 'und') "
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
                    "excerpt": (
                        str(row["excerpt"])
                        if search_mode == "sqlite_fts5_trigram_lexical"
                        else _literal_excerpt(str(row["excerpt"]), valid_query)
                    ),
                    "source_id": str(row["source_id"]),
                    "rank": float(row["rank"]),
                }
            )
            if len(results) == valid_limit:
                break
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "query": valid_query,
            "search_mode": search_mode,
            "language": valid_language,
            "count": len(results),
            "results": results,
        }

    def release_info(self, release: str = "current") -> JSONDict:
        """Return release provenance and deterministic aggregate counts."""
        with self._connect() as connection:
            release_id = self._resolve_release(connection, release)
            row = connection.execute(
                "SELECT * FROM release WHERE release_id = ?", (release_id,)
            ).fetchone()
            assert row is not None  # resolved directly above
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
            "source_manifest_sha256": str(row["source_manifest_sha256"]).upper(),
            "source_file_count": int(row["source_file_count"]),
            "source_total_bytes": int(row["source_total_bytes"]),
            "search_index": f"fts5_{self.search_tokenizer}",
            "concept_counts": [
                {
                    "scheme": str(item["scheme"]),
                    "edition": _edition_value(str(item["edition"])),
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
