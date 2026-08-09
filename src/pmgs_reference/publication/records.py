"""Bulk, lineage-preserving record assembly for public PMGS artifacts."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from pathlib import PurePosixPath
from typing import Any, cast

from pmgs_reference.normalization import group_key
from pmgs_reference.publication.model import GroupSpec, fragment_id, lookup_key
from pmgs_reference.publication.policy import SourcePresentation
from pmgs_reference.schema import SCHEMA_VERSION
from pmgs_reference.store import JSONDict, JSONValue

_SQL_BATCH = 500
_IPC_EDITION_PRIORITY = ("8U", "8B", "7", "7E", "6", "5", "4")


def current_ipc_edition(connection: sqlite3.Connection, release_id: str) -> str:
    rows = connection.execute(
        "SELECT DISTINCT edition FROM concept WHERE release_id = ? AND scheme = 'ipc'",
        (release_id,),
    ).fetchall()
    available = {str(row[0]) for row in rows}
    for edition in _IPC_EDITION_PRIORITY:
        if edition in available:
            return edition
    if not available:
        raise ValueError(f"release has no IPC concepts: {release_id}")
    return sorted(available)[-1]


def build_group_index(
    connection: sqlite3.Connection,
    release_id: str,
    latest_ipc_edition: str,
) -> dict[GroupSpec, list[int]]:
    """Map every publishable concept to its one or two deterministic public groups."""
    groups: dict[GroupSpec, list[int]] = defaultdict(list)
    rows = connection.execute(
        "SELECT concept_id, scheme, edition, normalized_code FROM concept "
        "WHERE release_id = ? AND concept_type NOT LIKE '%_reference' "
        "ORDER BY concept_id",
        (release_id,),
    )
    for row in rows:
        concept_id = int(row["concept_id"])
        scheme = str(row["scheme"])
        edition = str(row["edition"])
        code = str(row["normalized_code"])
        key = group_key(scheme, code)
        if scheme == "fterm":
            groups[GroupSpec("fterm", "", key)].append(concept_id)
        elif scheme == "fi":
            groups[GroupSpec("classification", "", key)].append(concept_id)
        elif scheme == "ipc":
            groups[GroupSpec("ipc", edition, key)].append(concept_id)
            if edition == latest_ipc_edition:
                groups[GroupSpec("classification", "", key)].append(concept_id)
    return dict(groups)


def _batches(values: Sequence[int], size: int = _SQL_BATCH) -> Iterator[Sequence[int]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _fetch_for_ids(
    connection: sqlite3.Connection,
    sql_template: str,
    concept_ids: Sequence[int],
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    for batch in _batches(concept_ids):
        placeholders = ",".join("?" for _ in batch)
        query = sql_template.replace("{concept_ids}", placeholders)
        rows.extend(cast(list[sqlite3.Row], connection.execute(query, batch).fetchall()))
    return rows


def _source_payload(row: sqlite3.Row, source: SourcePresentation) -> JSONDict:
    relative_path = str(row["relative_path"]).replace("\\", "/")
    return {
        "source_id": str(row["source_id"]),
        "title": PurePosixPath(relative_path).name,
        "relative_id": relative_path,
        "owner": source.owner,
        "original_url": source.source_url,
        "sha256": str(row["sha256"]).upper(),
        "attribution": source.attribution,
    }


def _language_value(value: object) -> str | None:
    return str(value) if value is not None else None


def load_group_record_map(
    connection: sqlite3.Connection,
    concept_ids: Sequence[int],
    source: SourcePresentation,
) -> dict[int, JSONDict]:
    """Load a concept set and all official, linked values in batched SQL."""
    if not concept_ids:
        return {}
    concept_rows = _fetch_for_ids(
        connection,
        "SELECT * FROM concept WHERE concept_id IN ({concept_ids})",
        concept_ids,
    )
    concept_rows.sort(
        key=lambda row: (str(row["scheme"]), str(row["edition"]), str(row["normalized_code"]))
    )
    records: dict[int, dict[str, Any]] = {}
    source_ids: dict[int, set[int]] = {}
    for row in concept_rows:
        concept_id = int(row["concept_id"])
        edition = str(row["edition"]) or None
        scheme = str(row["scheme"])
        code = str(row["normalized_code"])
        records[concept_id] = {
            "schema_version": SCHEMA_VERSION,
            "release_id": str(row["release_id"]),
            "lookup_key": lookup_key(scheme, edition, code),
            "scheme": scheme,
            "edition": edition,
            "code": code,
            "normalized_code": code,
            "labels": [],
            "texts": [],
            "properties": [],
            "relations": [],
            "documents": [],
            "sources": [],
            "fragment": fragment_id(scheme, edition, code),
            "canonical_urls": {},
        }
        source_ids[concept_id] = {int(row["source_file_id"])}

    text_rows = _fetch_for_ids(
        connection,
        "SELECT concept_id, language, kind, sequence_number, text, source_file_id, "
        "source_locator FROM concept_text WHERE concept_id IN ({concept_ids})",
        concept_ids,
    )
    text_rows.sort(
        key=lambda row: (
            int(row["concept_id"]),
            str(row["language"]),
            str(row["kind"]),
            int(row["sequence_number"]),
        )
    )
    for row in text_rows:
        concept_id = int(row["concept_id"])
        payload = {
            "language": str(row["language"]),
            "text": str(row["text"]),
            "provenance": "official",
        }
        if row["kind"] == "label":
            records[concept_id]["labels"].append(payload)
        else:
            records[concept_id]["texts"].append(
                {
                    "kind": str(row["kind"]),
                    **payload,
                    "source_file_id": int(row["source_file_id"]),
                    "locator": str(row["source_locator"]),
                }
            )
        source_ids[concept_id].add(int(row["source_file_id"]))

    property_rows = _fetch_for_ids(
        connection,
        "SELECT property_id, concept_id, name, value, language, source_file_id, source_locator "
        "FROM concept_property WHERE concept_id IN ({concept_ids})",
        concept_ids,
    )
    property_rows.sort(
        key=lambda row: (
            int(row["concept_id"]),
            str(row["name"]),
            int(row["property_id"]),
        )
    )
    for row in property_rows:
        concept_id = int(row["concept_id"])
        records[concept_id]["properties"].append(
            {
                "name": str(row["name"]),
                "value": str(row["value"]),
                "language": _language_value(row["language"]),
                "provenance": "official",
                "source_file_id": int(row["source_file_id"]),
                "locator": str(row["source_locator"]),
            }
        )
        source_ids[concept_id].add(int(row["source_file_id"]))

    relation_rows = _fetch_for_ids(
        connection,
        "SELECT r.from_concept_id AS concept_id, r.kind AS relation_type, target.scheme, "
        "target.edition, target.normalized_code, r.source_file_id FROM relation r "
        "JOIN concept target ON target.concept_id = r.to_concept_id "
        "WHERE r.from_concept_id IN ({concept_ids})",
        concept_ids,
    )
    child_rows = _fetch_for_ids(
        connection,
        "SELECT r.to_concept_id AS concept_id, 'child' AS relation_type, child.scheme, "
        "child.edition, child.normalized_code, r.source_file_id FROM relation r "
        "JOIN concept child ON child.concept_id = r.from_concept_id "
        "WHERE r.to_concept_id IN ({concept_ids}) AND r.kind = 'parent'",
        concept_ids,
    )
    all_relations = relation_rows + child_rows
    all_relations.sort(
        key=lambda row: (
            int(row["concept_id"]),
            str(row["relation_type"]),
            str(row["scheme"]),
            str(row["edition"]),
            str(row["normalized_code"]),
        )
    )
    for row in all_relations:
        concept_id = int(row["concept_id"])
        records[concept_id]["relations"].append(
            {
                "type": str(row["relation_type"]),
                "scheme": str(row["scheme"]),
                "code": str(row["normalized_code"]),
                "edition": str(row["edition"]) or None,
            }
        )
        source_ids[concept_id].add(int(row["source_file_id"]))

    document_rows = _fetch_for_ids(
        connection,
        "SELECT dl.concept_id, d.document_id, d.kind, d.language, d.title, d.page_count, "
        "dl.kind AS link_type, dl.source_file_id, d.source_file_id AS document_source_file_id "
        "FROM document_link dl JOIN document d ON d.document_id = dl.document_id "
        "WHERE dl.concept_id IN ({concept_ids})",
        concept_ids,
    )
    document_rows.sort(
        key=lambda row: (
            int(row["concept_id"]),
            str(row["kind"]),
            str(row["document_id"]),
            str(row["link_type"]),
        )
    )
    for row in document_rows:
        concept_id = int(row["concept_id"])
        records[concept_id]["documents"].append(
            {
                "document_id": str(row["document_id"]),
                "kind": str(row["kind"]),
                "language": str(row["language"]),
                "title": str(row["title"]),
                "page_count": int(row["page_count"]) if row["page_count"] is not None else None,
                "link_type": str(row["link_type"]),
            }
        )
        source_ids[concept_id].update(
            (int(row["source_file_id"]), int(row["document_source_file_id"]))
        )

    linked_text_rows = _fetch_for_ids(
        connection,
        "SELECT dl.concept_id, d.kind, d.language, dt.sequence_number, dt.text, "
        "d.source_file_id, dt.source_locator FROM document_link dl "
        "JOIN document d ON d.document_id = dl.document_id "
        "JOIN document_text dt ON dt.document_id = d.document_id "
        "AND dt.source_locator = dl.source_locator "
        "WHERE dl.concept_id IN ({concept_ids}) AND d.language IN ('ja', 'en')",
        concept_ids,
    )
    linked_text_rows.sort(
        key=lambda row: (
            int(row["concept_id"]),
            str(row["language"]),
            str(row["kind"]),
            int(row["sequence_number"]),
        )
    )
    linked_seen: dict[int, set[tuple[str, str, str, str]]] = defaultdict(set)
    for row in linked_text_rows:
        concept_id = int(row["concept_id"])
        identity = (
            str(row["kind"]),
            str(row["language"]),
            str(row["text"]),
            str(row["source_locator"]),
        )
        if identity in linked_seen[concept_id]:
            continue
        linked_seen[concept_id].add(identity)
        records[concept_id]["texts"].append(
            {
                "kind": identity[0],
                "language": identity[1],
                "text": identity[2],
                "provenance": "official",
                "source_file_id": int(row["source_file_id"]),
                "locator": identity[3],
            }
        )
        source_ids[concept_id].add(int(row["source_file_id"]))

    all_source_ids = sorted(set().union(*source_ids.values()))
    source_map: dict[int, JSONDict] = {}
    for batch in _batches(all_source_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT file_id, source_id, relative_path, sha256 FROM source_file "
            f"WHERE file_id IN ({placeholders})",
            batch,
        ).fetchall()
        for row in rows:
            source_map[int(row["file_id"])] = _source_payload(row, source)

    for concept_id, record in records.items():
        for collection_name in ("texts", "properties"):
            for item in record[collection_name]:
                file_id = int(item.pop("source_file_id"))
                item["source_id"] = str(source_map[file_id]["source_id"])
        record["texts"].sort(
            key=lambda item: (
                str(item["language"]),
                str(item["kind"]),
                str(item["locator"]),
                str(item["text"]),
            )
        )
        record["properties"].sort(
            key=lambda item: (
                str(item["name"]),
                str(item["language"] or ""),
                str(item["locator"]),
            )
        )
        record["sources"] = [
            source_map[file_id]
            for file_id in sorted(
                source_ids[concept_id], key=lambda item: str(source_map[item]["relative_id"])
            )
        ]

    return {
        int(row["concept_id"]): cast(JSONDict, records[int(row["concept_id"])])
        for row in concept_rows
    }


def load_group_records(
    connection: sqlite3.Connection,
    concept_ids: Sequence[int],
    source: SourcePresentation,
) -> list[JSONDict]:
    """Load one group's records in the stable public-record order."""
    records = load_group_record_map(connection, concept_ids, source)
    return sorted(
        records.values(),
        key=lambda record: (
            str(record["scheme"]),
            str(record["edition"] or ""),
            str(record["normalized_code"]),
        ),
    )


def has_language(record: JSONDict, language: str) -> bool:
    for key in ("labels", "texts"):
        values = record.get(key)
        if isinstance(values, list) and any(
            isinstance(item, dict) and item.get("language") == language for item in values
        ):
            return True
    properties = record.get("properties")
    return isinstance(properties, list) and any(
        isinstance(item, dict) and item.get("language") == language for item in properties
    )


def common_record(record: JSONDict, language: str) -> JSONDict:
    """Project a bilingual storage record into the shared language-specific API schema."""

    def filtered(key: str, include_neutral: bool = False) -> list[JSONValue]:
        value = record.get(key)
        if not isinstance(value, list):
            return []
        output: list[JSONValue] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            item_language = item.get("language")
            if item_language == language or (include_neutral and item_language is None):
                output.append(item)
        return output

    canonical_urls = record.get("canonical_urls")
    if not isinstance(canonical_urls, dict):
        raise ValueError("storage record is missing canonical URLs")
    canonical = canonical_urls.get(language) or canonical_urls.get("ja")
    if not isinstance(canonical, str):
        raise ValueError("storage record is missing a usable canonical URL")
    return {
        "schema_version": str(record["schema_version"]),
        "release_id": str(record["release_id"]),
        "scheme": str(record["scheme"]),
        "edition": record["edition"],
        "code": str(record["code"]),
        "normalized_code": str(record["normalized_code"]),
        "match_status": "exact",
        "labels": filtered("labels"),
        "texts": filtered("texts"),
        "properties": filtered("properties", include_neutral=True),
        "relations": record["relations"],
        "documents": record["documents"],
        "sources": record["sources"],
        "canonical_url": canonical,
    }


def render_record(record: JSONDict, language: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], common_record(record, language))
    payload["fragment"] = str(record["fragment"])
    payload["language"] = language
    return payload


def document_rows(connection: sqlite3.Connection, release_id: str) -> Iterable[sqlite3.Row]:
    return cast(
        Iterable[sqlite3.Row],
        connection.execute(
            "SELECT d.*, sf.source_id, sf.relative_path, sf.sha256 FROM document d "
            "JOIN source_file sf ON sf.file_id = d.source_file_id "
            "WHERE d.release_id = ? ORDER BY d.document_id",
            (release_id,),
        ),
    )


def load_document(
    connection: sqlite3.Connection,
    document_row: sqlite3.Row,
    source_presentation: SourcePresentation,
) -> tuple[JSONDict, list[JSONDict]]:
    """Load one official document and attach classification links at segment lineage."""
    document_id = str(document_row["document_id"])
    link_rows = connection.execute(
        "SELECT dl.source_locator, dl.kind, c.scheme, c.edition, c.normalized_code "
        "FROM document_link dl JOIN concept c ON c.concept_id = dl.concept_id "
        "WHERE dl.document_id = ? ORDER BY dl.source_locator, c.scheme, c.edition, "
        "c.normalized_code, dl.kind",
        (document_id,),
    ).fetchall()
    links_by_locator: dict[str, list[JSONValue]] = defaultdict(list)
    global_links: list[JSONValue] = []
    for row in link_rows:
        relation: JSONDict = {
            "scheme": str(row["scheme"]),
            "edition": str(row["edition"]) or None,
            "code": str(row["normalized_code"]),
            "type": str(row["kind"]),
        }
        locator = str(row["source_locator"])
        if locator == "file":
            global_links.append(relation)
        else:
            links_by_locator[locator].append(relation)

    segment_rows = connection.execute(
        "SELECT sequence_number, locator, heading, text, source_locator FROM document_text "
        "WHERE document_id = ? ORDER BY sequence_number",
        (document_id,),
    ).fetchall()
    segments: list[JSONDict] = []
    for row in segment_rows:
        locator = str(row["source_locator"])
        segments.append(
            {
                "sequence_number": int(row["sequence_number"]),
                "locator": str(row["locator"]),
                "heading": str(row["heading"]) if row["heading"] is not None else None,
                "text": str(row["text"]),
                "source_locator": locator,
                "related_classifications": [*global_links, *links_by_locator.get(locator, [])],
            }
        )
    source = _source_payload(document_row, source_presentation)
    language = str(document_row["language"])
    manifest: JSONDict = {
        "schema_version": SCHEMA_VERSION,
        "release_id": str(document_row["release_id"]),
        "document_id": document_id,
        "kind": str(document_row["kind"]),
        "language": language,
        "site_language": "en" if language == "en" else "ja",
        "title": str(document_row["title"]),
        "page_count": (
            int(document_row["page_count"]) if document_row["page_count"] is not None else None
        ),
        "metadata": cast(JSONValue, json.loads(str(document_row["metadata_json"]))),
        "segment_count": len(segments),
        "source": source,
    }
    return manifest, segments
