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
        "WHERE release_id = ? AND record_status = 'canonical' "
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


def _source_payload(row: sqlite3.Row, source: SourcePresentation | None = None) -> JSONDict:
    relative_path = str(row["relative_path"]).replace("\\", "/")
    columns = set(row.keys())
    if not {"owner", "original_url", "attribution"}.issubset(columns) and source is None:
        raise ValueError("source presentation metadata is missing")
    owner = str(row["owner"]) if "owner" in columns else cast(SourcePresentation, source).owner
    original_url = (
        str(row["original_url"])
        if "original_url" in columns
        else cast(SourcePresentation, source).source_url
    )
    attribution = (
        str(row["attribution"])
        if "attribution" in columns
        else cast(SourcePresentation, source).attribution
    )
    return {
        "source_id": str(row["source_id"]),
        "title": PurePosixPath(relative_path).name,
        "relative_id": relative_path,
        "owner": owner,
        "original_url": original_url,
        "sha256": str(row["sha256"]).upper(),
        "attribution": attribution,
    }


def _language_value(value: object) -> str | None:
    return str(value) if value is not None else None


def load_group_record_map(
    connection: sqlite3.Connection,
    concept_ids: Sequence[int],
    source: SourcePresentation,
) -> dict[int, JSONDict]:
    """Load stable concepts as revision-complete, single-chunk public bundles."""
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
    release_ids = {str(row["release_id"]) for row in concept_rows}
    if len(release_ids) != 1:
        raise ValueError("classification batch must belong to one release")
    release_id = next(iter(release_ids))
    release_row = connection.execute(
        "SELECT reference_date FROM release WHERE release_id = ?", (release_id,)
    ).fetchone()
    if release_row is None:
        raise ValueError("classification release is missing")
    reference_date = str(release_row["reference_date"])

    records: dict[int, dict[str, Any]] = {}
    revision_records: dict[int, dict[str, Any]] = {}
    revision_to_concept: dict[int, int] = {}
    source_ids: dict[int, set[int]] = {}
    for row in concept_rows:
        concept_id = int(row["concept_id"])
        edition = str(row["edition"]) or None
        scheme = str(row["scheme"])
        code = str(row["normalized_code"])
        records[concept_id] = {
            "schema_version": SCHEMA_VERSION,
            "release_id": str(row["release_id"]),
            "reference_date": reference_date,
            "lookup_key": lookup_key(scheme, edition, code),
            "scheme": scheme,
            "edition": edition,
            "code": code,
            "normalized_code": code,
            "record_status": str(row["record_status"]),
            "match_status": "not_valid_at_release",
            "version": None,
            "valid_from": None,
            "valid_to": None,
            "available_versions": [],
            "labels": [],
            "texts": [],
            "properties": [],
            "relations": [],
            "documents": [],
            "sources": [],
            "relation_count": 0,
            "relation_offset": 0,
            "relation_limit": 50,
            "next_relation_offset": None,
            "revision_records": [],
            "fragment": fragment_id(scheme, edition, code),
            "canonical_urls": {},
        }
        source_ids[concept_id] = {int(row["source_file_id"])}

    revision_rows = _fetch_for_ids(
        connection,
        "SELECT * FROM concept_revision WHERE concept_id IN ({concept_ids}) "
        "ORDER BY concept_id, version_indicator, valid_from, revision_id",
        concept_ids,
    )
    revision_source_ids: dict[int, set[int]] = {}
    for row in revision_rows:
        revision_id = int(row["revision_id"])
        concept_id = int(row["concept_id"])
        revision_to_concept[revision_id] = concept_id
        revision_source_ids[revision_id] = {int(row["source_file_id"])}
        revision_records[revision_id] = {
            "version": str(row["version_indicator"]) or None,
            "valid_from": str(row["valid_from"]) if row["valid_from"] is not None else None,
            "valid_to": str(row["valid_to"]) if row["valid_to"] is not None else None,
            "labels": [],
            "texts": [],
            "properties": [],
            "relations": [],
            "documents": [],
            "sources": [],
        }
        records[concept_id]["available_versions"].append(
            {
                "version": str(row["version_indicator"]) or None,
                "valid_from": (str(row["valid_from"]) if row["valid_from"] is not None else None),
                "valid_to": str(row["valid_to"]) if row["valid_to"] is not None else None,
            }
        )

    revision_ids = sorted(revision_records)
    if not revision_ids:
        raise ValueError("publishable concept has no revision")

    text_rows = _fetch_for_ids(
        connection,
        "SELECT revision_id, language, kind, sequence_number, text, source_file_id, "
        "source_locator FROM concept_text WHERE revision_id IN ({concept_ids})",
        revision_ids,
    )
    text_rows.sort(
        key=lambda row: (
            int(row["revision_id"]),
            str(row["language"]),
            str(row["kind"]),
            int(row["sequence_number"]),
        )
    )
    for row in text_rows:
        revision_id = int(row["revision_id"])
        payload = {
            "language": str(row["language"]),
            "text": str(row["text"]),
            "provenance": "official",
        }
        target = "labels" if row["kind"] == "label" else "texts"
        revision_records[revision_id][target].append(
            {
                "kind": str(row["kind"]),
                **payload,
                "source_file_id": int(row["source_file_id"]),
                "locator": str(row["source_locator"]),
                "_sequence_number": int(row["sequence_number"]),
            }
        )
        revision_source_ids[revision_id].add(int(row["source_file_id"]))

    property_rows = _fetch_for_ids(
        connection,
        "SELECT property_id, revision_id, name, value, language, source_file_id, source_locator "
        "FROM concept_property WHERE revision_id IN ({concept_ids})",
        revision_ids,
    )
    property_rows.sort(
        key=lambda row: (
            int(row["revision_id"]),
            str(row["name"]),
            int(row["property_id"]),
        )
    )
    for row in property_rows:
        revision_id = int(row["revision_id"])
        revision_records[revision_id]["properties"].append(
            {
                "name": str(row["name"]),
                "value": str(row["value"]),
                "language": _language_value(row["language"]),
                "provenance": "official",
                "source_file_id": int(row["source_file_id"]),
                "locator": str(row["source_locator"]),
            }
        )
        revision_source_ids[revision_id].add(int(row["source_file_id"]))

    relation_rows = _fetch_for_ids(
        connection,
        "SELECT r.from_concept_id AS concept_id, r.kind AS relation_type, target.scheme, "
        "target.edition, target.normalized_code, NULL AS version_indicator, r.source_file_id, "
        "r.source_locator FROM relation r "
        "JOIN concept target ON target.concept_id = r.to_concept_id "
        "WHERE r.from_concept_id IN ({concept_ids})",
        concept_ids,
    )
    child_rows = _fetch_for_ids(
        connection,
        "SELECT r.to_concept_id AS concept_id, 'child' AS relation_type, child.scheme, "
        "child.edition, child.normalized_code, NULL AS version_indicator, r.source_file_id, "
        "r.source_locator FROM relation r "
        "JOIN concept child ON child.concept_id = r.from_concept_id "
        "WHERE r.to_concept_id IN ({concept_ids}) AND r.kind = 'parent'",
        concept_ids,
    )
    concept_relations = relation_rows + child_rows
    relation_by_concept: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in concept_relations:
        relation_by_concept[int(row["concept_id"])].append(row)
    revision_relations = _fetch_for_ids(
        connection,
        "SELECT rr.from_revision_id AS revision_id, rr.kind AS relation_type, target.scheme, "
        "target.edition, target.normalized_code, target_revision.version_indicator, "
        "rr.source_file_id, rr.source_locator FROM revision_relation rr "
        "JOIN concept_revision target_revision ON target_revision.revision_id = rr.to_revision_id "
        "JOIN concept target ON target.concept_id = target_revision.concept_id "
        "WHERE rr.from_revision_id IN ({concept_ids})",
        revision_ids,
    )
    reverse_revision_relations = _fetch_for_ids(
        connection,
        "SELECT rr.to_revision_id AS revision_id, "
        "CASE rr.kind WHEN 'amended_to' THEN 'amended_from' ELSE rr.kind END AS relation_type, "
        "source.scheme, source.edition, source.normalized_code, source_revision.version_indicator, "
        "rr.source_file_id, rr.source_locator FROM revision_relation rr "
        "JOIN concept_revision source_revision "
        "ON source_revision.revision_id = rr.from_revision_id "
        "JOIN concept source ON source.concept_id = source_revision.concept_id "
        "WHERE rr.to_revision_id IN ({concept_ids})",
        revision_ids,
    )
    all_relations = revision_relations + reverse_revision_relations
    all_relations.sort(
        key=lambda row: (
            int(row["revision_id"]),
            str(row["relation_type"]),
            str(row["scheme"]),
            str(row["edition"]),
            str(row["normalized_code"]),
        )
    )
    for row in all_relations:
        revision_id = int(row["revision_id"])
        revision_records[revision_id]["relations"].append(
            {
                "type": str(row["relation_type"]),
                "scheme": str(row["scheme"]),
                "code": str(row["normalized_code"]),
                "edition": str(row["edition"]) or None,
                "version": str(row["version_indicator"]) or None,
                "source_file_id": int(row["source_file_id"]),
                "locator": str(row["source_locator"]),
            }
        )

    for revision_id, concept_id in revision_to_concept.items():
        for row in relation_by_concept.get(concept_id, []):
            revision_records[revision_id]["relations"].append(
                {
                    "type": str(row["relation_type"]),
                    "scheme": str(row["scheme"]),
                    "code": str(row["normalized_code"]),
                    "edition": str(row["edition"]) or None,
                    "version": None,
                    "source_file_id": int(row["source_file_id"]),
                    "locator": str(row["source_locator"]),
                }
            )

    concept_document_rows = _fetch_for_ids(
        connection,
        "SELECT dl.concept_id, d.document_id, d.kind, d.language, d.title, d.page_count, "
        "dl.kind AS link_type, dl.source_file_id, dl.source_locator, "
        "d.source_file_id AS document_source_file_id "
        "FROM document_link dl JOIN document d ON d.document_id = dl.document_id "
        "WHERE dl.concept_id IN ({concept_ids})",
        concept_ids,
    )
    revision_document_rows = _fetch_for_ids(
        connection,
        "SELECT drl.revision_id, d.document_id, d.kind, d.language, d.title, d.page_count, "
        "drl.kind AS link_type, drl.source_file_id, drl.source_locator, "
        "d.source_file_id AS document_source_file_id FROM document_revision_link drl "
        "JOIN document d ON d.document_id = drl.document_id "
        "WHERE drl.revision_id IN ({concept_ids})",
        revision_ids,
    )
    concept_docs: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in concept_document_rows:
        concept_docs[int(row["concept_id"])].append(row)
    document_rows = revision_document_rows
    document_rows.sort(
        key=lambda row: (
            int(row["revision_id"]),
            str(row["kind"]),
            str(row["document_id"]),
            str(row["link_type"]),
        )
    )
    for row in document_rows:
        revision_id = int(row["revision_id"])
        revision_records[revision_id]["documents"].append(
            {
                "document_id": str(row["document_id"]),
                "kind": str(row["kind"]),
                "language": str(row["language"]),
                "title": str(row["title"]),
                "page_count": int(row["page_count"]) if row["page_count"] is not None else None,
                "link_type": str(row["link_type"]),
                "source_file_id": int(row["source_file_id"]),
                "locator": str(row["source_locator"]),
            }
        )
        revision_source_ids[revision_id].update(
            (int(row["source_file_id"]), int(row["document_source_file_id"]))
        )

    for revision_id, concept_id in revision_to_concept.items():
        for row in concept_docs.get(concept_id, []):
            revision_records[revision_id]["documents"].append(
                {
                    "document_id": str(row["document_id"]),
                    "kind": str(row["kind"]),
                    "language": str(row["language"]),
                    "title": str(row["title"]),
                    "page_count": (
                        int(row["page_count"]) if row["page_count"] is not None else None
                    ),
                    "link_type": str(row["link_type"]),
                    "source_file_id": int(row["source_file_id"]),
                    "locator": str(row["source_locator"]),
                }
            )
            revision_source_ids[revision_id].update(
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
    revision_linked_text_rows = _fetch_for_ids(
        connection,
        "SELECT drl.revision_id, d.kind, d.language, dt.sequence_number, dt.text, "
        "d.source_file_id, dt.source_locator FROM document_revision_link drl "
        "JOIN document d ON d.document_id = drl.document_id "
        "JOIN document_text dt ON dt.document_id = d.document_id "
        "AND dt.source_locator = drl.source_locator "
        "WHERE drl.revision_id IN ({concept_ids}) AND d.language IN ('ja', 'en')",
        revision_ids,
    )
    linked_seen: dict[int, set[tuple[str, str, str, str]]] = defaultdict(set)
    concept_linked: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in linked_text_rows:
        concept_linked[int(row["concept_id"])].append(row)
    expanded_linked_rows: list[tuple[int, sqlite3.Row]] = [
        (int(row["revision_id"]), row) for row in revision_linked_text_rows
    ]
    for revision_id, concept_id in revision_to_concept.items():
        expanded_linked_rows.extend(
            (revision_id, row) for row in concept_linked.get(concept_id, [])
        )
    for revision_id, row in expanded_linked_rows:
        identity = (
            str(row["kind"]),
            str(row["language"]),
            str(row["text"]),
            str(row["source_locator"]),
        )
        if identity in linked_seen[revision_id]:
            continue
        linked_seen[revision_id].add(identity)
        revision_records[revision_id]["texts"].append(
            {
                "kind": identity[0],
                "language": identity[1],
                "text": identity[2],
                "provenance": "official",
                "source_file_id": int(row["source_file_id"]),
                "locator": identity[3],
                "_sequence_number": int(row["sequence_number"]),
            }
        )
        revision_source_ids[revision_id].add(int(row["source_file_id"]))

    for revision_id, revision_record in revision_records.items():
        relations_by_semantic_key: dict[tuple[str, str, str, str, str], JSONDict] = {}
        for relation in cast(list[JSONDict], revision_record["relations"]):
            semantic_key = (
                str(relation["type"]),
                str(relation["scheme"]),
                str(relation["edition"] or ""),
                str(relation["code"]),
                str(relation["version"] or ""),
            )
            current = relations_by_semantic_key.get(semantic_key)
            lineage_key = (cast(int, relation["source_file_id"]), str(relation["locator"]))
            if current is None or lineage_key < (
                cast(int, current["source_file_id"]),
                str(current["locator"]),
            ):
                relations_by_semantic_key[semantic_key] = relation
        revision_record["relations"] = [
            relations_by_semantic_key[key] for key in sorted(relations_by_semantic_key)
        ]
        revision_source_ids[revision_id].update(
            cast(int, relation["source_file_id"])
            for relation in cast(list[JSONDict], revision_record["relations"])
        )

    all_source_ids = sorted(set().union(*source_ids.values(), *revision_source_ids.values()))
    source_map: dict[int, JSONDict] = {}
    for batch in _batches(all_source_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = connection.execute(
            "SELECT sf.file_id, sf.source_id, sf.relative_path, sf.sha256, "
            "rs.owner, rs.original_url, rs.attribution FROM source_file sf "
            "JOIN release_source rs ON rs.release_id = sf.release_id "
            f"WHERE sf.file_id IN ({placeholders})",
            batch,
        ).fetchall()
        for row in rows:
            source_map[int(row["file_id"])] = _source_payload(row)

    for revision_id, revision_record in revision_records.items():
        for collection_name in ("labels", "texts", "properties", "relations", "documents"):
            for item in revision_record[collection_name]:
                file_id = int(item.pop("source_file_id"))
                item["source_id"] = str(source_map[file_id]["source_id"])
        revision_record["labels"].sort(
            key=lambda item: (
                str(item["language"]),
                int(item["_sequence_number"]),
                str(item["locator"]),
                str(item["text"]),
            )
        )
        revision_record["texts"].sort(
            key=lambda item: (
                str(item["language"]),
                str(item["kind"]),
                int(item["_sequence_number"]),
                str(item["locator"]),
                str(item["text"]),
            )
        )
        for item in (*revision_record["labels"], *revision_record["texts"]):
            item.pop("_sequence_number")
        revision_record["properties"].sort(
            key=lambda item: (
                str(item["name"]),
                str(item["language"] or ""),
                str(item["locator"]),
            )
        )
        revision_record["relations"].sort(
            key=lambda item: (
                str(item["type"]),
                str(item["scheme"]),
                str(item["edition"] or ""),
                str(item["code"]),
                str(item["version"] or ""),
            )
        )
        revision_record["documents"].sort(
            key=lambda item: (str(item["kind"]), str(item["document_id"]), str(item["link_type"]))
        )
        revision_record["sources"] = [
            source_map[file_id]
            for file_id in sorted(
                revision_source_ids[revision_id],
                key=lambda item: str(source_map[item]["relative_id"]),
            )
        ]

    revisions_by_concept: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for revision_id, revision_record in revision_records.items():
        revisions_by_concept[revision_to_concept[revision_id]].append(revision_record)
    for concept_id, record in records.items():
        revisions = revisions_by_concept[concept_id]
        revisions.sort(key=lambda item: (str(item["version"] or ""), str(item["valid_from"] or "")))
        record["revision_records"] = revisions
        active = [
            item
            for item in revisions
            if (item["valid_from"] is None or str(item["valid_from"]) <= reference_date)
            and (item["valid_to"] is None or str(item["valid_to"]) >= reference_date)
        ]
        if len(active) > 1:
            raise ValueError("multiple revisions are active at the release reference date")
        record["sources"] = [
            source_map[file_id]
            for file_id in sorted(
                source_ids[concept_id], key=lambda item: str(source_map[item]["relative_id"])
            )
        ]
        if active:
            selected = active[0]
            for key in (
                "version",
                "valid_from",
                "valid_to",
                "labels",
                "texts",
                "properties",
                "relations",
                "documents",
                "sources",
            ):
                record[key] = selected[key]
            record["match_status"] = "exact"
            record["relation_count"] = len(selected["relations"])
            record["relations"] = selected["relations"][:50]
            record["next_relation_offset"] = 50 if len(selected["relations"]) > 50 else None

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
        "reference_date": str(record["reference_date"]),
        "scheme": str(record["scheme"]),
        "edition": record["edition"],
        "code": str(record["code"]),
        "normalized_code": str(record["normalized_code"]),
        "record_status": record["record_status"],
        "match_status": str(record["match_status"]),
        "version": record["version"],
        "valid_from": record["valid_from"],
        "valid_to": record["valid_to"],
        "available_versions": record["available_versions"],
        "labels": filtered("labels"),
        "texts": filtered("texts"),
        "properties": filtered("properties", include_neutral=True),
        "relation_count": record["relation_count"],
        "relation_offset": record["relation_offset"],
        "relation_limit": record["relation_limit"],
        "relations_truncated": bool(record["next_relation_offset"] is not None),
        "next_relation_offset": record["next_relation_offset"],
        "relations": record["relations"],
        "documents": record["documents"],
        "sources": record["sources"],
        "canonical_url": canonical,
    }


def render_record(record: JSONDict, language: str) -> dict[str, Any]:
    payload = cast(dict[str, Any], common_record(record, language))
    histories: list[JSONValue] = []
    revisions = record.get("revision_records")
    if isinstance(revisions, list):
        for item in revisions:
            if not isinstance(item, dict) or item.get("version") == record.get("version"):
                continue
            revision_labels = item.get("labels")
            revision_texts = item.get("texts")
            histories.append(
                {
                    "version": item.get("version"),
                    "valid_from": item.get("valid_from"),
                    "valid_to": item.get("valid_to"),
                    "labels": [
                        value
                        for value in revision_labels
                        if isinstance(value, dict) and value.get("language") == language
                    ]
                    if isinstance(revision_labels, list)
                    else [],
                    "texts": [
                        value
                        for value in revision_texts
                        if isinstance(value, dict) and value.get("language") == language
                    ]
                    if isinstance(revision_texts, list)
                    else [],
                }
            )
    payload["revision_records"] = histories
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
