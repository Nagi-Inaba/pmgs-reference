"""Deterministic public HTML, Markdown, JSON, manifest, and discovery export."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from pmgs_reference.publication.model import (
    CSS_CONTENT_TYPE,
    HTML_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    TEXT_CONTENT_TYPE,
    XML_CONTENT_TYPE,
    GroupSpec,
    ObjectMetadata,
    OutputWriter,
    canonical_json_bytes,
    chunk_json_bytes,
)
from pmgs_reference.publication.policy import (
    PublicationPolicy,
    SourcePresentation,
    load_publication_policy,
)
from pmgs_reference.publication.records import (
    build_group_index,
    current_ipc_edition,
    document_rows,
    has_language,
    load_document,
    load_group_record_map,
    render_record,
)
from pmgs_reference.publication.render import (
    classification_html,
    classification_markdown,
    document_html,
    document_markdown,
    home_html,
    llms_text,
    openapi_document,
    robots_text,
    sitemap_documents,
    stylesheet,
)
from pmgs_reference.schema import SCHEMA_VERSION
from pmgs_reference.store import JSONDict, JSONValue, PMGSStore

_MIN_CHUNK_BYTES = 4_096
_MAX_CHUNK_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_JSON_CHUNK_BYTES = 256 * 1024
_GROUP_BATCH_CONCEPTS = 1_000
_WRITE_WORKERS = 32
_DOCUMENT_WRITE_WINDOW = 64
_SQLITE_CACHE_KIB = 1024 * 1024
_SQLITE_MMAP_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _Chunk:
    chunk_id: str
    items: list[JSONDict]
    data: bytes


@dataclass(frozen=True, slots=True)
class _WriteResult:
    writer: OutputWriter
    sitemap_urls: list[str]
    chunk_count: int
    oversized_chunk_count: int


@dataclass(frozen=True, slots=True)
class ExportResult:
    release_id: str
    generated_at: str
    base_url: str
    max_json_chunk_bytes: int
    object_count: int
    total_bytes: int
    group_count: int
    classification_chunk_count: int
    document_count: int
    document_chunk_count: int
    oversized_chunk_count: int
    tree_sha256: str
    release_manifest_sha256: str

    def as_dict(self) -> JSONDict:
        return {
            "release_id": self.release_id,
            "generated_at": self.generated_at,
            "base_url": self.base_url,
            "max_json_chunk_bytes": self.max_json_chunk_bytes,
            "object_count": self.object_count,
            "total_bytes": self.total_bytes,
            "group_count": self.group_count,
            "classification_chunk_count": self.classification_chunk_count,
            "document_count": self.document_count,
            "document_chunk_count": self.document_chunk_count,
            "oversized_chunk_count": self.oversized_chunk_count,
            "tree_sha256": self.tree_sha256,
            "release_manifest_sha256": self.release_manifest_sha256,
        }


def _clean_base_url(base_url: str) -> str:
    clean = base_url.strip().rstrip("/")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ValueError("base_url must be an HTTP(S) origin without a path")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("base_url must not contain credentials, query, or fragment")
    return clean


def _read_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA cache_size = -{_SQLITE_CACHE_KIB}")
    connection.execute(f"PRAGMA mmap_size = {_SQLITE_MMAP_BYTES}")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _group_batches(
    group_index: dict[GroupSpec, list[int]],
    max_concepts: int,
) -> Iterator[tuple[list[GroupSpec], list[int]]]:
    """Yield sorted, whole-group batches capped by unique concept count when possible."""
    if max_concepts < 1:
        raise ValueError("max_concepts must be positive")
    specs: list[GroupSpec] = []
    concept_ids: set[int] = set()
    for spec in sorted(group_index):
        spec_ids = set(group_index[spec])
        if specs and len(concept_ids | spec_ids) > max_concepts:
            yield specs, sorted(concept_ids)
            specs = []
            concept_ids = set()
        specs.append(spec)
        concept_ids.update(spec_ids)
        if len(concept_ids) >= max_concepts:
            yield specs, sorted(concept_ids)
            specs = []
            concept_ids = set()
    if specs:
        yield specs, sorted(concept_ids)


def _header_size(header: JSONDict, item_bytes: list[bytes], array_key: str) -> int:
    return len(chunk_json_bytes(header, item_bytes, array_key=array_key))


def _assign_canonical_urls(
    record: JSONDict,
    spec: GroupSpec,
    chunk_id: str,
    base_url: str,
) -> bytes:
    fragment = str(record["fragment"])
    canonical_urls: JSONDict = {"ja": f"{base_url}{spec.site_path('ja', chunk_id)}#{fragment}"}
    if has_language(record, "en"):
        canonical_urls["en"] = f"{base_url}{spec.site_path('en', chunk_id)}#{fragment}"
    record["canonical_urls"] = canonical_urls
    return canonical_json_bytes(record).removesuffix(b"\n")


def _split_group_records(
    records: list[JSONDict],
    spec: GroupSpec,
    release_id: str,
    base_url: str,
    max_bytes: int,
) -> tuple[list[_Chunk], int]:
    chunks: list[_Chunk] = []
    oversized = 0
    current_records: list[JSONDict] = []
    current_bytes: list[bytes] = []
    chunk_number = 1

    def header(chunk_id: str) -> JSONDict:
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "group_kind": spec.kind,
            "edition": spec.edition or None,
            "group_key": spec.group_key,
            "chunk_id": chunk_id,
        }

    def flush() -> None:
        if not current_records:
            return
        chunk_id = f"{chunk_number:03d}"
        data = chunk_json_bytes(header(chunk_id), current_bytes)
        chunks.append(_Chunk(chunk_id, list(current_records), data))

    for record in records:
        chunk_id = f"{chunk_number:03d}"
        serialized = _assign_canonical_urls(record, spec, chunk_id, base_url)
        candidate = [*current_bytes, serialized]
        if current_records and _header_size(header(chunk_id), candidate, "records") > max_bytes:
            flush()
            chunk_number += 1
            chunk_id = f"{chunk_number:03d}"
            current_records = []
            current_bytes = []
            serialized = _assign_canonical_urls(record, spec, chunk_id, base_url)
        current_records.append(record)
        current_bytes.append(serialized)
        if (
            len(current_records) == 1
            and _header_size(header(chunk_id), current_bytes, "records") > max_bytes
        ):
            oversized += 1
    flush()
    return chunks, oversized


def _language_chunk_urls(
    chunks: list[_Chunk], spec: GroupSpec, language: str, base_url: str
) -> dict[str, str]:
    output: dict[str, str] = {}
    for chunk in chunks:
        if language == "ja" or any(has_language(record, language) for record in chunk.items):
            output[chunk.chunk_id] = f"{base_url}{spec.site_path(language, chunk.chunk_id)}"
    return output


def _write_group(
    writer: OutputWriter,
    *,
    release_id: str,
    spec: GroupSpec,
    records: list[JSONDict],
    base_url: str,
    source: SourcePresentation,
    max_bytes: int,
    sitemap_urls: list[str],
) -> tuple[int, int]:
    chunks, oversized = _split_group_records(records, spec, release_id, base_url, max_bytes)
    release_prefix = f"releases/{release_id}"
    language_urls = {
        language: _language_chunk_urls(chunks, spec, language, base_url)
        for language in ("ja", "en")
    }
    chunk_manifest: list[JSONValue] = []
    for chunk in chunks:
        json_key = f"{release_prefix}/{spec.object_prefix}/{chunk.chunk_id}.json"
        json_metadata = writer.write_bytes(json_key, chunk.data, "application/json; charset=utf-8")
        site: JSONDict = {}
        for language in ("ja", "en"):
            page_url = language_urls[language].get(chunk.chunk_id)
            if page_url is None:
                continue
            ordered_ids = list(language_urls[language])
            position = ordered_ids.index(chunk.chunk_id)
            previous_url = (
                language_urls[language].get(ordered_ids[position - 1]) if position else None
            )
            next_url = (
                language_urls[language].get(ordered_ids[position + 1])
                if position + 1 < len(ordered_ids)
                else None
            )
            page_records = [
                render_record(record, language)
                for record in chunk.items
                if language == "ja" or has_language(record, language)
            ]
            html_key = f"{release_prefix}/{spec.site_key(language, chunk.chunk_id, 'html')}"
            markdown_key = f"{release_prefix}/{spec.site_key(language, chunk.chunk_id, 'md')}"
            html_metadata = writer.write_text(
                html_key,
                classification_html(
                    spec=spec,
                    language=language,
                    records=page_records,
                    page_url=page_url,
                    previous_url=previous_url,
                    next_url=next_url,
                    release_id=release_id,
                    base_url=base_url,
                    source=source,
                ),
                HTML_CONTENT_TYPE,
            )
            markdown_metadata = writer.write_text(
                markdown_key,
                classification_markdown(
                    spec=spec,
                    language=language,
                    records=page_records,
                    page_url=page_url,
                    previous_url=previous_url,
                    next_url=next_url,
                    release_id=release_id,
                    source=source,
                ),
                MARKDOWN_CONTENT_TYPE,
            )
            sitemap_urls.append(page_url)
            site[language] = {
                "url": page_url,
                "html_key": html_key,
                "html_bytes": html_metadata.bytes,
                "html_sha256": html_metadata.sha256,
                "markdown_key": markdown_key,
                "markdown_bytes": markdown_metadata.bytes,
                "markdown_sha256": markdown_metadata.sha256,
            }
        chunk_manifest.append(
            {
                "chunk_id": chunk.chunk_id,
                "first_lookup_key": str(chunk.items[0]["lookup_key"]),
                "last_lookup_key": str(chunk.items[-1]["lookup_key"]),
                "record_count": len(chunk.items),
                "json_key": json_key,
                "json_bytes": json_metadata.bytes,
                "json_sha256": json_metadata.sha256,
                "site": site,
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "group_kind": spec.kind,
        "edition": spec.edition or None,
        "group_key": spec.group_key,
        "record_count": len(records),
        "chunks": chunk_manifest,
    }
    writer.write_json(f"{release_prefix}/{spec.object_prefix}/manifest.json", manifest)
    return len(chunks), oversized


def _write_group_isolated(
    root: Path,
    *,
    release_id: str,
    spec: GroupSpec,
    records: list[JSONDict],
    base_url: str,
    source: SourcePresentation,
    max_bytes: int,
) -> _WriteResult:
    writer = OutputWriter(root)
    sitemap_urls: list[str] = []
    chunk_count, oversized = _write_group(
        writer,
        release_id=release_id,
        spec=spec,
        records=records,
        base_url=base_url,
        source=source,
        max_bytes=max_bytes,
        sitemap_urls=sitemap_urls,
    )
    return _WriteResult(writer, sitemap_urls, chunk_count, oversized)


def _split_document_segments(
    document_id: str,
    release_id: str,
    segments: list[JSONDict],
    max_bytes: int,
) -> tuple[list[_Chunk], int]:
    chunks: list[_Chunk] = []
    oversized = 0
    current_segments: list[JSONDict] = []
    current_bytes: list[bytes] = []
    chunk_number = 1

    def header(chunk_id: str) -> JSONDict:
        return {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
        }

    def flush() -> None:
        if not current_segments and chunks:
            return
        chunk_id = f"{chunk_number:03d}"
        data = chunk_json_bytes(header(chunk_id), current_bytes, array_key="segments")
        chunks.append(_Chunk(chunk_id, list(current_segments), data))

    for segment in segments:
        chunk_id = f"{chunk_number:03d}"
        serialized = canonical_json_bytes(segment).removesuffix(b"\n")
        candidate = [*current_bytes, serialized]
        if current_segments and _header_size(header(chunk_id), candidate, "segments") > max_bytes:
            flush()
            chunk_number += 1
            current_segments = []
            current_bytes = []
        current_segments.append(segment)
        current_bytes.append(serialized)
        if (
            len(current_segments) == 1
            and _header_size(header(chunk_id), current_bytes, "segments") > max_bytes
        ):
            oversized += 1
    flush()
    return chunks, oversized


def _sequence_value(chunk: _Chunk, first: bool) -> int | None:
    if not chunk.items:
        return None
    item = chunk.items[0] if first else chunk.items[-1]
    value = item.get("sequence_number")
    return int(value) if isinstance(value, int) else None


def _page_values(chunk: _Chunk) -> list[JSONValue]:
    pages: set[int] = set()
    for item in chunk.items:
        for key in ("locator", "source_locator"):
            value = item.get(key)
            if isinstance(value, str) and (match := re.fullmatch(r"page:([1-9][0-9]*)", value)):
                pages.add(int(match.group(1)))
    return [cast(JSONValue, page) for page in sorted(pages)]


def _write_document(
    writer: OutputWriter,
    *,
    release_id: str,
    manifest_base: JSONDict,
    segments: list[JSONDict],
    base_url: str,
    source: SourcePresentation,
    max_bytes: int,
    sitemap_urls: list[str],
) -> tuple[int, int]:
    document_id = str(manifest_base["document_id"])
    language = str(manifest_base["site_language"])
    chunks, oversized = _split_document_segments(document_id, release_id, segments, max_bytes)
    release_prefix = f"releases/{release_id}"
    object_prefix = f"documents/{document_id}"
    base_path = f"/{language}/documents/{document_id}"
    chunk_urls = {
        chunk.chunk_id: f"{base_url}{base_path}"
        if chunk.chunk_id == "001"
        else f"{base_url}{base_path}/{chunk.chunk_id}"
        for chunk in chunks
    }
    chunk_entries: list[JSONValue] = []
    for index, chunk in enumerate(chunks):
        json_key = f"{release_prefix}/{object_prefix}/{chunk.chunk_id}.json"
        json_metadata = writer.write_bytes(json_key, chunk.data, "application/json; charset=utf-8")
        page_url = chunk_urls[chunk.chunk_id]
        previous_url = chunk_urls[chunks[index - 1].chunk_id] if index else None
        next_url = chunk_urls[chunks[index + 1].chunk_id] if index + 1 < len(chunks) else None
        site_prefix = f"site/{language}/documents/{document_id}/{chunk.chunk_id}"
        html_key = f"{release_prefix}/{site_prefix}.html"
        markdown_key = f"{release_prefix}/{site_prefix}.md"
        render_segments = [cast(dict[str, Any], item) for item in chunk.items]
        html_metadata = writer.write_text(
            html_key,
            document_html(
                manifest=cast(dict[str, Any], manifest_base),
                segments=render_segments,
                page_url=page_url,
                previous_url=previous_url,
                next_url=next_url,
                source=source,
            ),
            HTML_CONTENT_TYPE,
        )
        markdown_metadata = writer.write_text(
            markdown_key,
            document_markdown(
                manifest=cast(dict[str, Any], manifest_base),
                segments=render_segments,
                page_url=page_url,
                previous_url=previous_url,
                next_url=next_url,
                source=source,
            ),
            MARKDOWN_CONTENT_TYPE,
        )
        sitemap_urls.append(page_url)
        chunk_entries.append(
            {
                "chunk_id": chunk.chunk_id,
                "first_sequence": _sequence_value(chunk, True),
                "last_sequence": _sequence_value(chunk, False),
                "pages": _page_values(chunk),
                "segment_count": len(chunk.items),
                "json_key": json_key,
                "json_bytes": json_metadata.bytes,
                "json_sha256": json_metadata.sha256,
                "url": page_url,
                "html_key": html_key,
                "html_bytes": html_metadata.bytes,
                "html_sha256": html_metadata.sha256,
                "markdown_key": markdown_key,
                "markdown_bytes": markdown_metadata.bytes,
                "markdown_sha256": markdown_metadata.sha256,
            }
        )
    document_manifest = {**manifest_base, "chunks": chunk_entries}
    writer.write_json(f"{release_prefix}/{object_prefix}/manifest.json", document_manifest)
    return len(chunks), oversized


def _write_document_isolated(
    root: Path,
    *,
    release_id: str,
    manifest_base: JSONDict,
    segments: list[JSONDict],
    base_url: str,
    source: SourcePresentation,
    max_bytes: int,
) -> _WriteResult:
    writer = OutputWriter(root)
    sitemap_urls: list[str] = []
    chunk_count, oversized = _write_document(
        writer,
        release_id=release_id,
        manifest_base=manifest_base,
        segments=segments,
        base_url=base_url,
        source=source,
        max_bytes=max_bytes,
        sitemap_urls=sitemap_urls,
    )
    return _WriteResult(writer, sitemap_urls, chunk_count, oversized)


def _coverage(
    connection: sqlite3.Connection,
    release_id: str,
    group_index: dict[GroupSpec, list[int]],
) -> JSONDict:
    coverage: JSONDict = {}
    rows = connection.execute(
        "SELECT scheme, edition, COUNT(*) AS count FROM concept WHERE release_id = ? "
        "AND concept_type NOT LIKE '%_reference' GROUP BY scheme, edition "
        "ORDER BY scheme, edition",
        (release_id,),
    ).fetchall()
    for row in rows:
        edition = str(row["edition"]) or "current"
        coverage[f"classification.{row['scheme']}.{edition}"] = int(row["count"])
    coverage["classification.reference_only_excluded"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM concept WHERE release_id = ? AND concept_type LIKE '%_reference'",
            (release_id,),
        ).fetchone()[0]
    )
    coverage["classification.unique_public"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM concept WHERE release_id = ? "
            "AND concept_type NOT LIKE '%_reference'",
            (release_id,),
        ).fetchone()[0]
    )
    coverage["classification.storage_records"] = sum(len(values) for values in group_index.values())
    coverage["classification.groups"] = len(group_index)
    document_counts = connection.execute(
        "SELECT language, COUNT(*) AS count FROM document WHERE release_id = ? "
        "GROUP BY language ORDER BY language",
        (release_id,),
    ).fetchall()
    coverage["documents.total"] = sum(int(row["count"]) for row in document_counts)
    for row in document_counts:
        coverage[f"documents.language.{row['language']}"] = int(row["count"])
    coverage["documents.segments"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM document_text dt JOIN document d "
            "ON d.document_id = dt.document_id WHERE d.release_id = ?",
            (release_id,),
        ).fetchone()[0]
    )
    return coverage


def _tree_sha256(objects: list[ObjectMetadata]) -> str:
    """Hash a newly generated tree from already measured object digests."""
    digest = hashlib.sha256()
    for item in sorted(objects, key=lambda value: value.key):
        key = item.key.encode("utf-8")
        digest.update(len(key).to_bytes(4, "big"))
        digest.update(key)
        digest.update(bytes.fromhex(item.sha256))
    return digest.hexdigest().upper()


def _release_row(connection: sqlite3.Connection, release_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM release WHERE release_id = ?", (release_id,)).fetchone()
    if row is None:
        raise ValueError(f"release not found in database: {release_id}")
    return cast(sqlite3.Row, row)


def _validate_source_attribution(
    connection: sqlite3.Connection,
    release_id: str,
    source: SourcePresentation,
) -> None:
    rows = connection.execute(
        "SELECT re.value FROM reference_entry re "
        "JOIN source_file sf ON sf.file_id = re.source_file_id "
        "WHERE sf.release_id = ? AND re.category = 'copyright' AND re.key = 'COPYRGHT'",
        (release_id,),
    ).fetchall()
    notices = {str(row["value"]).strip() for row in rows if str(row["value"]).strip()}
    if len(notices) != 1:
        raise ValueError("database must contain exactly one non-empty COPYRGHT notice")
    if source.attribution != next(iter(notices)):
        raise ValueError("policy attribution does not match the database COPYRGHT notice")


def _write_report(path: Path, result: ExportResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(result.as_dict()))
    temporary.replace(path)


def export_public(
    database: Path,
    policy_path: Path,
    output_path: Path,
    *,
    base_url: str,
    max_json_chunk_bytes: int = DEFAULT_MAX_JSON_CHUNK_BYTES,
    report_path: Path | None = None,
) -> ExportResult:
    """Generate a complete, deterministic, local public-release candidate."""
    clean_base_url = _clean_base_url(base_url)
    if not _MIN_CHUNK_BYTES <= max_json_chunk_bytes <= _MAX_CHUNK_BYTES:
        raise ValueError(
            f"max_json_chunk_bytes must be between {_MIN_CHUNK_BYTES} and {_MAX_CHUNK_BYTES}"
        )
    database = database.resolve()
    PMGSStore.open(database)
    policy: PublicationPolicy = load_publication_policy(policy_path.resolve())
    output_path = output_path.resolve()
    if output_path.exists():
        raise FileExistsError(f"public output already exists: {output_path}")

    connection = _read_connection(database)
    try:
        release = _release_row(connection, policy.release_id)
        release_id = str(release["release_id"])
        _validate_source_attribution(connection, release_id, policy.source)
        output_path.mkdir(parents=True)
        writer = OutputWriter(output_path)
        sitemap_urls = [f"{clean_base_url}/"]
        latest_ipc = current_ipc_edition(connection, release_id)
        group_index = build_group_index(connection, release_id, latest_ipc)
        coverage = _coverage(connection, release_id, group_index)
        group_count = 0
        classification_chunks = 0
        document_count = 0
        document_chunks = 0
        oversized_chunks = 0

        with ThreadPoolExecutor(max_workers=_WRITE_WORKERS) as executor:
            for specs, concept_ids in _group_batches(group_index, _GROUP_BATCH_CONCEPTS):
                record_map = load_group_record_map(connection, concept_ids, policy.source)
                group_futures: list[Future[_WriteResult]] = []
                for spec in specs:
                    records = sorted(
                        (dict(record_map[concept_id]) for concept_id in group_index[spec]),
                        key=lambda record: (
                            str(record["scheme"]),
                            str(record["edition"] or ""),
                            str(record["normalized_code"]),
                        ),
                    )
                    group_futures.append(
                        executor.submit(
                            _write_group_isolated,
                            output_path,
                            release_id=release_id,
                            spec=spec,
                            records=records,
                            base_url=clean_base_url,
                            source=policy.source,
                            max_bytes=max_json_chunk_bytes,
                        )
                    )
                for future in group_futures:
                    write_result = future.result()
                    writer.merge(write_result.writer)
                    sitemap_urls.extend(write_result.sitemap_urls)
                    group_count += 1
                    classification_chunks += write_result.chunk_count
                    oversized_chunks += write_result.oversized_chunk_count

            document_futures: deque[Future[_WriteResult]] = deque()
            for document_row in document_rows(connection, release_id):
                manifest_base, segments = load_document(connection, document_row, policy.source)
                document_futures.append(
                    executor.submit(
                        _write_document_isolated,
                        output_path,
                        release_id=release_id,
                        manifest_base=manifest_base,
                        segments=segments,
                        base_url=clean_base_url,
                        source=policy.source,
                        max_bytes=max_json_chunk_bytes,
                    )
                )
                document_count += 1
                if len(document_futures) >= _DOCUMENT_WRITE_WINDOW:
                    write_result = document_futures.popleft().result()
                    writer.merge(write_result.writer)
                    sitemap_urls.extend(write_result.sitemap_urls)
                    document_chunks += write_result.chunk_count
                    oversized_chunks += write_result.oversized_chunk_count
            while document_futures:
                write_result = document_futures.popleft().result()
                writer.merge(write_result.writer)
                sitemap_urls.extend(write_result.sitemap_urls)
                document_chunks += write_result.chunk_count
                oversized_chunks += write_result.oversized_chunk_count

        coverage["classification.chunks"] = classification_chunks
        coverage["documents.chunks"] = document_chunks
        coverage["json.oversized_chunks"] = oversized_chunks
        release_prefix = f"releases/{release_id}"
        writer.write_json(f"{release_prefix}/coverage.json", coverage)
        writer.write_json(f"{release_prefix}/publication-policy.json", policy.payload)
        writer.write_json("api/v1/coverage.json", coverage)
        writer.write_json(
            "api/v1/releases.json",
            {
                "schema_version": SCHEMA_VERSION,
                "current_release": release_id,
                "releases": [release_id],
            },
        )
        writer.write_text(
            "index.html", home_html(clean_base_url, release_id, policy.source), HTML_CONTENT_TYPE
        )
        writer.write_text("assets/style.css", stylesheet(), CSS_CONTENT_TYPE)
        writer.write_json("openapi.json", openapi_document(clean_base_url, release_id))
        writer.write_text(
            "llms.txt", llms_text(clean_base_url, release_id, policy.source), TEXT_CONTENT_TYPE
        )
        writer.write_text("robots.txt", robots_text(clean_base_url), TEXT_CONTENT_TYPE)
        for key, content in sitemap_documents(clean_base_url, sitemap_urls).items():
            writer.write_text(key, content, XML_CONTENT_TYPE)

        database_schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        manifest_payload: JSONDict = {
            "schema_version": SCHEMA_VERSION,
            "release_id": release_id,
            "source_manifest_sha256": str(release["source_manifest_sha256"]).upper(),
            "database_schema_version": database_schema_version,
            "generated_at": policy.generated_at,
            "base_url": clean_base_url,
            "max_json_chunk_bytes": max_json_chunk_bytes,
            "publication_policy_sha256": policy.sha256,
            "coverage": coverage,
            "objects": [
                item.as_dict() for item in sorted(writer.objects, key=lambda value: value.key)
            ],
        }
        manifest_metadata = writer.write_json(
            f"{release_prefix}/manifest.json", manifest_payload, record=False
        )
    finally:
        connection.close()

    result = ExportResult(
        release_id=release_id,
        generated_at=policy.generated_at,
        base_url=clean_base_url,
        max_json_chunk_bytes=max_json_chunk_bytes,
        object_count=len(writer.objects) + 1,
        total_bytes=sum(item.bytes for item in writer.objects) + manifest_metadata.bytes,
        group_count=group_count,
        classification_chunk_count=classification_chunks,
        document_count=document_count,
        document_chunk_count=document_chunks,
        oversized_chunk_count=oversized_chunks,
        tree_sha256=_tree_sha256([*writer.objects, manifest_metadata]),
        release_manifest_sha256=manifest_metadata.sha256,
    )
    if report_path is not None:
        _write_report(report_path.resolve(), result)
    return result
