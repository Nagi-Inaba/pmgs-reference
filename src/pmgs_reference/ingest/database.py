"""Low-level deterministic writer for the PMGS SQLite store."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

from pmgs_reference.ingest.inventory import SourceInventory, SourceManifestEntry
from pmgs_reference.normalization import normalize_code
from pmgs_reference.schema import SCHEMA_SQL, SCHEMA_VERSION

Language = Literal["ja", "en", "und"]
IssueSeverity = Literal["info", "warning", "error"]
RecordStatus = Literal["canonical", "reference_only"]
_VERSION = re.compile(r"^[0-9]{4}\.[0-9]{2}$")


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


def normalize_version_indicator(value: str) -> str:
    raw = value.strip()
    if raw.startswith("(") != raw.endswith(")"):
        raise ValueError("version indicator parentheses must be balanced")
    clean = raw[1:-1].strip() if raw.startswith("(") else raw
    if clean and not _VERSION.fullmatch(clean):
        raise ValueError("version indicator must be empty or YYYY.MM")
    return clean


def normalize_iso_date(value: str) -> str | None:
    clean = value.strip()
    if not clean:
        return None
    try:
        if re.fullmatch(r"[0-9]{8}", clean):
            parsed = dt.datetime.strptime(clean, "%Y%m%d").date()
        else:
            parsed = dt.date.fromisoformat(clean)
    except ValueError as exc:
        raise ValueError("validity date must be YYYYMMDD or ISO YYYY-MM-DD") from exc
    return parsed.isoformat()


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    value = cursor.lastrowid
    if value is None:
        raise RuntimeError("SQLite insert did not return a row id")
    return value


class DatabaseWriter:
    """Own inserts and stable in-memory identity maps during one build."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        release_id: str,
        reference_date: str,
        inventory: SourceInventory,
    ) -> None:
        self.connection = connection
        self.release_id = release_id
        self.reference_date = reference_date
        self.inventory = inventory
        self.sources: dict[str, SourceRef] = {}
        self.concepts: dict[tuple[str, str, str], int] = {}
        self.revisions: dict[tuple[int, str], int] = {}
        self.documents: dict[str, str] = {}
        self.ipc_versions: dict[tuple[str, str], int] = {}

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA_SQL)
        self.connection.execute(
            "INSERT INTO release VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.release_id,
                SCHEMA_VERSION,
                self.reference_date,
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
        record_status: RecordStatus = "canonical",
    ) -> int | None:
        normalized = normalize_code(scheme, code)
        if not normalized:
            return None
        key = (scheme, edition, normalized)
        existing = self.concepts.get(key)
        if existing is not None:
            if record_status == "canonical":
                self.connection.execute(
                    """
                    UPDATE concept
                    SET concept_type = ?, record_status = 'canonical', source_file_id = ?,
                        source_locator = ?, code = ?
                    WHERE concept_id = ? AND record_status = 'reference_only'
                    """,
                    (concept_type, source.file_id, source_locator, code.strip(), existing),
                )
            if edition != "8U" or record_status == "reference_only":
                self.add_revision(
                    concept_id=existing,
                    version_indicator="",
                    valid_from=None,
                    valid_to=None,
                    level=level,
                    sequence_number=sequence_number,
                    source=source,
                    source_locator=source_locator,
                )
            return existing
        cursor = self.connection.execute(
            """
            INSERT INTO concept(
                release_id, scheme, edition, code, normalized_code, concept_type,
                record_status, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.release_id,
                scheme,
                edition,
                code.strip(),
                normalized,
                concept_type,
                record_status,
                source.file_id,
                source_locator,
            ),
        )
        concept_id = _lastrowid(cursor)
        self.concepts[key] = concept_id
        if edition != "8U" or record_status == "reference_only":
            self.add_revision(
                concept_id=concept_id,
                version_indicator="",
                valid_from=None,
                valid_to=None,
                level=level,
                sequence_number=sequence_number,
                source=source,
                source_locator=source_locator,
            )
        return concept_id

    def add_revision(
        self,
        *,
        concept_id: int,
        version_indicator: str,
        valid_from: str | None,
        valid_to: str | None,
        level: int | None,
        sequence_number: int | None,
        source: SourceRef,
        source_locator: str,
    ) -> int:
        version = normalize_version_indicator(version_indicator)
        start = normalize_iso_date(valid_from or "")
        end = normalize_iso_date(valid_to or "")
        if start is not None and end is not None and start > end:
            raise ValueError("revision valid_from must not be after valid_to")
        key = (concept_id, version)
        existing = self.revisions.get(key)
        if existing is not None:
            row = self.connection.execute(
                "SELECT valid_from, valid_to, level, sequence_number "
                "FROM concept_revision WHERE revision_id = ?",
                (existing,),
            ).fetchone()
            assert row is not None
            if (row[0], row[1], row[2], row[3]) != (
                start,
                end,
                level,
                sequence_number,
            ):
                self.add_issue(
                    severity="error",
                    code="REVISION_CONFLICT",
                    message=(
                        "duplicate concept revision has conflicting validity, level, or sequence"
                    ),
                    source=source,
                    source_locator=source_locator,
                )
            return existing
        cursor = self.connection.execute(
            """
            INSERT INTO concept_revision(
                concept_id, version_indicator, valid_from, valid_to, level, sequence_number,
                source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                concept_id,
                version,
                start,
                end,
                level,
                sequence_number,
                source.file_id,
                source_locator,
            ),
        )
        revision_id = _lastrowid(cursor)
        self.revisions[key] = revision_id
        concept = self.connection.execute(
            "SELECT scheme, normalized_code FROM concept WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        assert concept is not None
        if concept[0] == "ipc" and version:
            self.ipc_versions[(str(concept[1]), version)] = revision_id
        return revision_id

    def find_concept(self, scheme: str, edition: str, code: str) -> int | None:
        return self.concepts.get((scheme, edition, normalize_code(scheme, code)))

    def base_revision(self, concept_id: int) -> int | None:
        return self.revisions.get((concept_id, ""))

    def revision_structure(self, revision_id: int) -> tuple[int | None, int | None]:
        row = self.connection.execute(
            "SELECT level, sequence_number FROM concept_revision WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown concept revision: {revision_id}")
        return row[0], row[1]

    def find_revision(self, scheme: str, edition: str, code: str, version: str) -> int | None:
        concept_id = self.find_concept(scheme, edition, code)
        if concept_id is None:
            return None
        return self.revisions.get((concept_id, normalize_version_indicator(version)))

    def find_latest_ipc(self, code: str) -> int | None:
        normalized = normalize_code("ipc", code)
        for edition in ("8U", "8B", "7", "7E", "6", "5", "4"):
            concept_id = self.concepts.get(("ipc", edition, normalized))
            if concept_id is not None:
                return concept_id
        return None

    def add_concept_text(
        self,
        *,
        revision_id: int,
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
                revision_id=revision_id,
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
                revision_id, language, kind, sequence_number, text,
                translation_status, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, 'official', ?, ?)
            """,
            (revision_id, language, kind, sequence_number, clean, source.file_id, source_locator),
        )
        text_id = _lastrowid(cursor)
        self.connection.execute(
            "INSERT INTO concept_text_fts(rowid, text, revision_id, language, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            (text_id, clean, revision_id, language, kind),
        )
        return text_id

    def add_property(
        self,
        *,
        revision_id: int,
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
                revision_id, name, value, language, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (revision_id, name, clean, language, source.file_id, source_locator),
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
        if kind == "parent":
            row = self.connection.execute(
                "SELECT to_concept_id FROM relation WHERE from_concept_id = ? AND kind = 'parent'",
                (from_concept_id,),
            ).fetchone()
            if row is not None and int(row[0]) != to_concept_id:
                self.add_issue(
                    severity="error",
                    code="HIERARCHY_PARENT_CONFLICT",
                    message="concept revisions resolve to different hierarchy parents",
                    source=source,
                    source_locator=source_locator,
                )
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

    def add_revision_relation(
        self,
        *,
        from_revision_id: int | None,
        to_revision_id: int | None,
        kind: str,
        source: SourceRef,
        source_locator: str,
    ) -> bool:
        if from_revision_id is None or to_revision_id is None:
            return False
        if from_revision_id == to_revision_id:
            self.add_issue(
                severity="error",
                code="REVISION_RELATION_SELF",
                message="revision relation endpoints must be distinct",
                source=source,
                source_locator=source_locator,
            )
            return False
        self.connection.execute(
            """
            INSERT OR IGNORE INTO revision_relation(
                from_revision_id, to_revision_id, kind, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (from_revision_id, to_revision_id, kind, source.file_id, source_locator),
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

    def add_document_revision_link(
        self,
        *,
        document_id: str,
        revision_id: int | None,
        kind: str,
        source: SourceRef,
        source_locator: str,
    ) -> bool:
        if revision_id is None:
            return False
        self.connection.execute(
            """
            INSERT OR IGNORE INTO document_revision_link(
                document_id, revision_id, kind, source_file_id, source_locator
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, revision_id, kind, source.file_id, source_locator),
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

    def add_release_source(self, *, attribution: str, source: SourceRef) -> None:
        clean = normalized_text(attribution)
        if not clean:
            raise ValueError("COPYRGHT attribution must not be empty")
        self.connection.execute(
            """
            INSERT INTO release_source(
                release_id, owner, original_url, attribution, source_file_id, source_locator
            ) VALUES (?, 'JPO',
                'https://www.jpo.go.jp/system/laws/sesaku/data/download.html', ?, ?, 'file')
            """,
            (self.release_id, clean, source.file_id),
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
