"""Low-level deterministic writer for the PMGS SQLite store."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Literal

from pmgs_reference.ingest.inventory import SourceInventory, SourceManifestEntry
from pmgs_reference.normalization import normalize_code
from pmgs_reference.schema import SCHEMA_SQL, SCHEMA_VERSION

Language = Literal["ja", "en", "und"]
IssueSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class SourceRef:
    file_id: int
    source_id: str
    relative_path: str
    data_group: str
    file_type: str


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    value = cursor.lastrowid
    if value is None:
        raise RuntimeError("SQLite insert did not return a row id")
    return value


class DatabaseWriter:
    """Owns inserts and stable in-memory identity maps during one build."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        release_id: str,
        inventory: SourceInventory,
    ) -> None:
        self.connection = connection
        self.release_id = release_id
        self.inventory = inventory
        self.sources: dict[str, SourceRef] = {}
        self.concepts: dict[tuple[str, str, str], int] = {}
        self.documents: dict[str, str] = {}
        self.ipc_versions: dict[tuple[str, str], int] = {}

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.execute(
            "INSERT INTO release VALUES (?, ?, ?, ?, ?)",
            (
                self.release_id,
                SCHEMA_VERSION,
                self.inventory.logical_sha256,
                len(self.inventory.entries),
                self.inventory.total_bytes,
            ),
        )
        for entry in self.inventory.entries:
            cursor = self.connection.execute(
                """
                INSERT INTO source_file(
                    release_id, source_id, relative_path, size_bytes, sha256,
                    file_type, encoding, data_group, parser, status, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.release_id,
                    entry.source_id,
                    entry.relative_path,
                    entry.size_bytes,
                    entry.sha256,
                    entry.file_type,
                    entry.encoding,
                    entry.data_group,
                    entry.parser,
                    entry.status,
                    entry.error,
                ),
            )
            file_id = _lastrowid(cursor)
            self.sources[entry.relative_path] = SourceRef(
                file_id=file_id,
                source_id=entry.source_id,
                relative_path=entry.relative_path,
                data_group=entry.data_group,
                file_type=entry.file_type,
            )

    def source_for(self, entry: SourceManifestEntry) -> SourceRef:
        return self.sources[entry.relative_path]

    def add_source_record(
        self, source: SourceRef, record_number: int, record_kind: str, payload: object
    ) -> None:
        self.connection.execute(
            "INSERT INTO source_record VALUES (?, ?, ?, ?)",
            (source.file_id, record_number, record_kind, canonical_json(payload)),
        )

    def add_concept(
        self,
        *,
        scheme: str,
        edition: str,
        code: str,
        concept_type: str,
        level: int | None,
        sequence_number: int | None,
        source: SourceRef,
        source_locator: str,
    ) -> int | None:
        normalized = normalize_code(scheme, code)
        if not normalized:
            return None
        key = (scheme, edition, normalized)
        existing = self.concepts.get(key)
        if existing is not None:
            return existing
        cursor = self.connection.execute(
            """
            INSERT INTO concept(
                release_id, scheme, edition, code, normalized_code, concept_type,
                level, sequence_number, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.release_id,
                scheme,
                edition,
                code.strip(),
                normalized,
                concept_type,
                level,
                sequence_number,
                source.file_id,
                source_locator,
            ),
        )
        concept_id = _lastrowid(cursor)
        self.concepts[key] = concept_id
        return concept_id

    def find_concept(self, scheme: str, edition: str, code: str) -> int | None:
        normalized = normalize_code(scheme, code)
        return self.concepts.get((scheme, edition, normalized))

    def find_latest_ipc(self, code: str) -> int | None:
        normalized = normalize_code("ipc", code)
        for edition in ("8U", "8B", "7", "7E", "6", "5", "4"):
            concept_id = self.concepts.get(("ipc", edition, normalized))
            if concept_id is not None:
                return concept_id
        return None

    def register_ipc_version(self, concept_id: int, code: str, version: str) -> None:
        clean_version = version.strip().strip("()")
        if clean_version:
            self.ipc_versions[(normalize_code("ipc", code), clean_version)] = concept_id

    def add_concept_text(
        self,
        *,
        concept_id: int,
        language: Literal["ja", "en"],
        kind: str,
        sequence_number: int,
        text: str,
        source: SourceRef,
        source_locator: str,
    ) -> int | None:
        clean = normalized_text(text)
        if clean == "(Not Translated)":
            self.add_property(
                concept_id=concept_id,
                name=f"{kind}_translation_status",
                value="not_translated",
                language=language,
                source=source,
                source_locator=source_locator,
            )
            return None
        if not clean:
            return None
        cursor = self.connection.execute(
            """
            INSERT INTO concept_text(
                concept_id, language, kind, sequence_number, text,
                translation_status, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, 'official', ?, ?)
            """,
            (
                concept_id,
                language,
                kind,
                sequence_number,
                clean,
                source.file_id,
                source_locator,
            ),
        )
        text_id = _lastrowid(cursor)
        self.connection.execute(
            "INSERT INTO concept_text_fts(rowid, text, concept_id, language, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (text_id, clean, concept_id, language, kind),
        )
        return text_id

    def add_property(
        self,
        *,
        concept_id: int,
        name: str,
        value: str,
        language: str | None,
        source: SourceRef,
        source_locator: str,
    ) -> None:
        clean = normalized_text(value)
        if not clean:
            return
        self.connection.execute(
            """
            INSERT INTO concept_property(
                concept_id, name, value, language, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (concept_id, name, clean, language, source.file_id, source_locator),
        )

    def add_relation(
        self,
        *,
        from_concept_id: int | None,
        to_concept_id: int | None,
        kind: str,
        source: SourceRef,
        source_locator: str,
    ) -> bool:
        if from_concept_id is None or to_concept_id is None:
            return False
        self.connection.execute(
            """
            INSERT OR IGNORE INTO relation(
                from_concept_id, to_concept_id, kind, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (from_concept_id, to_concept_id, kind, source.file_id, source_locator),
        )
        return True

    def add_document(
        self,
        *,
        source: SourceRef,
        kind: str,
        language: Language,
        title: str,
        page_count: int | None = None,
        metadata: object | None = None,
    ) -> str:
        existing = self.documents.get(source.relative_path)
        if existing is not None:
            return existing
        document_id = f"doc-{source.source_id.removeprefix('src-')}"
        self.connection.execute(
            "INSERT INTO document VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id,
                self.release_id,
                kind,
                language,
                normalized_text(title) or source.relative_path,
                page_count,
                source.file_id,
                canonical_json(metadata or {}),
            ),
        )
        self.documents[source.relative_path] = document_id
        return document_id

    def add_document_text(
        self,
        *,
        document_id: str,
        sequence_number: int,
        locator: str,
        heading: str | None,
        text: str,
        source_locator: str,
    ) -> int | None:
        clean = normalized_text(text)
        if not clean or clean == "(Not Translated)":
            return None
        cursor = self.connection.execute(
            """
            INSERT INTO document_text(
                document_id, sequence_number, locator, heading, text, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                sequence_number,
                locator,
                normalized_text(heading) if heading else None,
                clean,
                source_locator,
            ),
        )
        text_id = _lastrowid(cursor)
        self.connection.execute(
            "INSERT INTO document_text_fts(rowid, text, document_id, sequence_number) "
            "VALUES (?, ?, ?, ?)",
            (text_id, clean, document_id, sequence_number),
        )
        return text_id

    def add_document_link(
        self,
        *,
        document_id: str,
        concept_id: int | None,
        kind: str,
        source: SourceRef,
        source_locator: str,
    ) -> bool:
        if concept_id is None:
            return False
        self.connection.execute(
            """
            INSERT OR IGNORE INTO document_link(
                document_id, concept_id, kind, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, concept_id, kind, source.file_id, source_locator),
        )
        return True

    def add_reference_entry(
        self,
        *,
        category: str,
        key: str,
        language: Language,
        value: str,
        source: SourceRef,
        source_locator: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO reference_entry(
                category, key, language, value, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                key.strip(),
                language,
                normalized_text(value),
                source.file_id,
                source_locator,
            ),
        )

    def add_issue(
        self,
        *,
        severity: IssueSeverity,
        code: str,
        message: str,
        source: SourceRef | None = None,
        source_locator: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO build_issue(severity, code, message, source_file_id, source_locator) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                severity,
                code,
                normalized_text(message),
                source.file_id if source else None,
                source_locator,
            ),
        )
