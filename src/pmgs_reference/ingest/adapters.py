"""Format- and data-group-specific PMGS ingestion adapters."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

import pymupdf
from lxml import etree

from pmgs_reference.ingest.csv_support import portable_csv_field_size_limit
from pmgs_reference.ingest.database import (
    DatabaseWriter,
    SourceRef,
    normalize_version_indicator,
    normalized_text,
)
from pmgs_reference.ingest.html_support import parse_html
from pmgs_reference.ingest.inventory import SourceManifestEntry
from pmgs_reference.normalization import normalize_code

_THEME_CODE = re.compile(r"^[0-9][A-Z][0-9]{3}$")
_INT = re.compile(r"^-?[0-9]+$")
_XML_DECLARATION_TEXT = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>", re.IGNORECASE)


def _integer(value: str) -> int | None:
    clean = value.strip()
    return int(clean) if _INT.fullmatch(clean) else None


def _csv_rows(path: Path) -> Iterator[list[str]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp932")
    with portable_csv_field_size_limit():
        yield from csv.reader(io.StringIO(text, newline=""))


def _parse_xml(raw: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        return etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError:
        text = raw.decode("cp932")
        text = _XML_DECLARATION_TEXT.sub("", text, count=1)
        fallback = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(text, parser=fallback)


def _concept_type(code: str, level: int | None, scheme: str) -> str:
    normalized = normalize_code(scheme, code)
    if scheme == "fterm":
        if len(normalized) == 5:
            return "theme"
        if len(normalized) == 7:
            return "aspect"
        return "term"
    if len(normalized) == 1:
        return "section"
    if len(normalized) == 3:
        return "class"
    if len(normalized) == 4:
        return "subclass"
    if level is not None and level <= 4:
        return "subclass"
    return "group"


def _add_parent_from_stack(
    writer: DatabaseWriter,
    stack: list[tuple[int, int]],
    level: int | None,
    concept_id: int,
    source: SourceRef,
    locator: str,
) -> None:
    if level is None:
        return
    while stack and stack[-1][0] >= level:
        stack.pop()
    if stack:
        writer.add_relation(
            from_concept_id=concept_id,
            to_concept_id=stack[-1][1],
            kind="parent",
            source=source,
            source_locator=locator,
        )
    stack.append((level, concept_id))


def _process_fi_codes(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    stack: list[tuple[int, int]] = []
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        if len(row) != 5:
            writer.add_issue(
                severity="error",
                code="FI_COLUMN_COUNT",
                message=f"expected 5 columns, found {len(row)}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        code = row[0]
        level = _integer(row[4])
        locator = f"row:{row_number}"
        was_known = writer.find_concept("fi", "", code) is not None
        concept_id = writer.add_concept(
            scheme="fi",
            edition="",
            code=code,
            concept_type=_concept_type(code, level, "fi"),
            level=level,
            sequence_number=_integer(row[1]),
            source=source,
            source_locator=locator,
        )
        if concept_id is not None and not was_known:
            _add_parent_from_stack(writer, stack, level, concept_id, source, locator)
            revision_id = writer.base_revision(concept_id)
            assert revision_id is not None
            writer.add_property(
                revision_id=revision_id,
                name="fi_marker",
                value=row[2],
                language=None,
                source=source,
                source_locator=locator,
            )
            writer.add_property(
                revision_id=revision_id,
                name="fi_status",
                value=row[3],
                language=None,
                source=source,
                source_locator=locator,
            )


def _process_themes(writer: DatabaseWriter, source: SourceRef, path: Path, language: str) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        if len(row) != 8:
            writer.add_issue(
                severity="error",
                code="THEME_COLUMN_COUNT",
                message=f"expected 8 columns, found {len(row)}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        code = normalize_code("fterm", row[0])
        if not _THEME_CODE.fullmatch(code):
            continue
        locator = f"row:{row_number}"
        sequence_number = _integer(row[1])
        if language == "en":
            concept_id = writer.find_concept("fterm", "", code)
            if concept_id is None:
                writer.add_issue(
                    severity="error",
                    code="THEME_TRANSLATION_CONCEPT_MISSING",
                    message="English theme row has no canonical Japanese concept",
                    source=source,
                    source_locator=locator,
                )
                continue
            revision_id = writer.base_revision(concept_id)
            if revision_id is None:
                writer.add_issue(
                    severity="error",
                    code="THEME_TRANSLATION_REVISION_MISSING",
                    message="English theme row has no canonical Japanese revision",
                    source=source,
                    source_locator=locator,
                )
                continue
            _canonical_level, canonical_sequence = writer.revision_structure(revision_id)
            if canonical_sequence != sequence_number:
                writer.add_issue(
                    severity="warning",
                    code="THEME_TRANSLATION_SEQUENCE_MISMATCH",
                    message="English theme sequence differs from canonical Japanese source",
                    source=source,
                    source_locator=locator,
                )
            writer.add_concept_text(
                revision_id=revision_id,
                language="en",
                kind="label",
                sequence_number=1,
                text=row[6],
                source=source,
                source_locator=locator,
            )
            for name, value in (("fi_scope", row[5]), ("remarks", row[7])):
                writer.add_property(
                    revision_id=revision_id,
                    name=name,
                    value=value,
                    language="en",
                    source=source,
                    source_locator=locator,
                )
            continue
        concept_id = writer.add_concept(
            scheme="fterm",
            edition="",
            code=code,
            concept_type="theme",
            level=0,
            sequence_number=sequence_number,
            source=source,
            source_locator=locator,
        )
        if concept_id is None:
            continue
        revision_id = writer.base_revision(concept_id)
        assert revision_id is not None
        writer.add_concept_text(
            revision_id=revision_id,
            language="ja",
            kind="label",
            sequence_number=1,
            text=row[6],
            source=source,
            source_locator=locator,
        )
        for name, value in (("fi_scope", row[5]), ("remarks", row[7])):
            writer.add_property(
                revision_id=revision_id,
                name=name,
                value=value,
                language="ja",
                source=source,
                source_locator=locator,
            )


def _fterm_columns(row: list[str]) -> tuple[str, str, str, str, str] | None:
    if len(row) < 5:
        return None
    return row[0], row[1], row[2], ",".join(row[3:-1]), row[-1]


def _process_fterms(writer: DatabaseWriter, source: SourceRef, path: Path, language: str) -> None:
    stack: list[tuple[int, int]] = []
    current_aspect = ""
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        fields = _fterm_columns(row)
        if fields is None:
            writer.add_issue(
                severity="error",
                code="FTERM_COLUMN_COUNT",
                message=f"expected at least 5 columns, found {len(row)}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        raw_code, raw_sequence, raw_depth, label, fi_scope = fields
        code = normalize_code("fterm", raw_code)
        if len(code) < 9:
            continue
        locator = f"row:{row_number}"
        theme_code = code[:5]
        aspect_code = code[:7]
        depth = _integer(raw_depth) or 0
        sequence_number = _integer(raw_sequence)
        if language == "en":
            existing_term = writer.find_concept("fterm", "", code)
            if existing_term is None:
                writer.add_issue(
                    severity="error",
                    code="FTERM_TRANSLATION_CONCEPT_MISSING",
                    message="English F-term row has no canonical Japanese concept",
                    source=source,
                    source_locator=locator,
                )
                continue
            existing_revision = writer.base_revision(existing_term)
            if existing_revision is None:
                writer.add_issue(
                    severity="error",
                    code="FTERM_TRANSLATION_REVISION_MISSING",
                    message="English F-term row has no canonical Japanese revision",
                    source=source,
                    source_locator=locator,
                )
                continue
            canonical_level, canonical_sequence = writer.revision_structure(existing_revision)
            if canonical_sequence != sequence_number:
                writer.add_issue(
                    severity="error",
                    code="FTERM_TRANSLATION_SEQUENCE_MISMATCH",
                    message="English F-term sequence differs from canonical Japanese structure",
                    source=source,
                    source_locator=locator,
                )
                continue
            if canonical_level != depth + 2:
                writer.add_issue(
                    severity="warning",
                    code="FTERM_TRANSLATION_DEPTH_MISMATCH",
                    message="English F-term depth differs from canonical Japanese structure",
                    source=source,
                    source_locator=locator,
                )
            writer.add_concept_text(
                revision_id=existing_revision,
                language="en",
                kind="label",
                sequence_number=1,
                text=label,
                source=source,
                source_locator=locator,
            )
            writer.add_property(
                revision_id=existing_revision,
                name="fi_scope",
                value=fi_scope,
                language="en",
                source=source,
                source_locator=locator,
            )
            continue

        theme_id = writer.find_concept("fterm", "", theme_code)
        if theme_id is None:
            theme_id = writer.add_concept(
                scheme="fterm",
                edition="",
                code=theme_code,
                concept_type="theme",
                level=0,
                sequence_number=None,
                source=source,
                source_locator=locator,
            )
        aspect_id = writer.add_concept(
            scheme="fterm",
            edition="",
            code=aspect_code,
            concept_type="aspect",
            level=1,
            sequence_number=None,
            source=source,
            source_locator=locator,
        )
        writer.add_relation(
            from_concept_id=aspect_id,
            to_concept_id=theme_id,
            kind="parent",
            source=source,
            source_locator=locator,
        )
        term_id = writer.add_concept(
            scheme="fterm",
            edition="",
            code=code,
            concept_type="term",
            level=depth + 2,
            sequence_number=sequence_number,
            source=source,
            source_locator=locator,
        )
        if term_id is None:
            continue
        revision_id = writer.base_revision(term_id)
        assert revision_id is not None
        if current_aspect != aspect_code:
            stack = []
            current_aspect = aspect_code
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent_id = stack[-1][1] if stack else aspect_id
        writer.add_relation(
            from_concept_id=term_id,
            to_concept_id=parent_id,
            kind="parent",
            source=source,
            source_locator=locator,
        )
        stack.append((depth, term_id))
        writer.add_concept_text(
            revision_id=revision_id,
            language="en" if language == "en" else "ja",
            kind="label",
            sequence_number=1,
            text=label,
            source=source,
            source_locator=locator,
        )
        writer.add_property(
            revision_id=revision_id,
            name="fi_scope",
            value=fi_scope,
            language=language,
            source=source,
            source_locator=locator,
        )


def _ipc_shape(group: str, row: list[str]) -> tuple[str, str, str, str, str, str, str, str]:
    if group == "IPC/IPC8U_TEXT" and len(row) == 11:
        return row[0], row[1], row[2], row[3], row[4], row[10], row[7], row[8]
    if group == "IPC/IPC8B_TEXT" and len(row) == 9:
        return row[0], row[1], row[2], row[3], row[4], row[8], "", ""
    if len(row) == 6:
        return row[0], "", row[1], row[2], row[3], row[5], "", ""
    raise ValueError(f"unsupported IPC row with {len(row)} columns")


def _process_ipc(
    writer: DatabaseWriter, source: SourceRef, path: Path, edition: str, language: str
) -> None:
    stack: list[tuple[int, int]] = []
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        locator = f"row:{row_number}"
        try:
            code, version, sequence, text_type, raw_level, text, valid_from, valid_to = _ipc_shape(
                source.data_group, row
            )
        except ValueError as exc:
            writer.add_issue(
                severity="error",
                code="IPC_COLUMN_COUNT",
                message=str(exc),
                source=source,
                source_locator=locator,
            )
            continue
        text_sequence = _integer(sequence)
        if text_sequence is None or text_sequence <= 0:
            writer.add_issue(
                severity="error",
                code="IPC_SEQUENCE_INVALID",
                message="IPC text sequence must be a positive integer",
                source=source,
                source_locator=locator,
            )
            continue
        level = _integer(raw_level)
        was_known = writer.find_concept("ipc", edition, code) is not None
        concept_id = writer.add_concept(
            scheme="ipc",
            edition=edition,
            code=code,
            concept_type=_concept_type(code, level, "ipc"),
            level=level,
            # IPCのsequenceは同一revision内の本文行順であり、revision自体の
            # 構造属性ではない。実値はconcept_textへ保存する。
            sequence_number=None,
            source=source,
            source_locator=locator,
        )
        if concept_id is None:
            continue
        revision_id = writer.add_revision(
            concept_id=concept_id,
            version_indicator=version if edition == "8U" else "",
            valid_from=valid_from or None,
            valid_to=valid_to or None,
            level=level,
            sequence_number=None,
            source=source,
            source_locator=locator,
        )
        if not was_known:
            _add_parent_from_stack(writer, stack, level, concept_id, source, locator)
        else:
            _add_parent_from_stack(writer, stack, level, concept_id, source, locator)
        writer.add_concept_text(
            revision_id=revision_id,
            language="en" if language == "en" else "ja",
            kind=f"ipc_text_type_{text_type.strip() or 'unknown'}",
            sequence_number=text_sequence,
            text=text,
            source=source,
            source_locator=locator,
        )


def _process_fi_text(writer: DatabaseWriter, source: SourceRef, path: Path, language: str) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        locator = f"row:{row_number}"
        if len(row) != 7:
            writer.add_issue(
                severity="error",
                code="FI_TEXT_COLUMN_COUNT",
                message=f"expected 7 columns, found {len(row)}",
                source=source,
                source_locator=locator,
            )
            continue
        concept_id = writer.find_concept("fi", "", row[0])
        if concept_id is None:
            writer.add_issue(
                severity="warning",
                code="FI_TEXT_CONCEPT_MISSING",
                message=f"FI concept not found: {normalize_code('fi', row[0])}",
                source=source,
                source_locator=locator,
            )
            continue
        revision_id = writer.base_revision(concept_id)
        assert revision_id is not None
        writer.add_concept_text(
            revision_id=revision_id,
            language="en" if language == "en" else "ja",
            kind=f"fi_text_type_{row[2].strip() or 'unknown'}",
            sequence_number=_integer(row[1]) or 1,
            text=row[6],
            source=source,
            source_locator=locator,
        )


def _process_document_csv(
    writer: DatabaseWriter,
    source: SourceRef,
    path: Path,
    *,
    kind: str,
    language: str,
    expected_columns: int,
    code_column: int,
    sequence_column: int,
    text_column: int,
    text_kind_column: int,
    scheme: str,
) -> None:
    document_id = writer.add_document(
        source=source,
        kind=kind,
        language="en" if language == "en" else "ja",
        title=path.stem,
    )
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        locator = f"row:{row_number}"
        if len(row) != expected_columns:
            writer.add_issue(
                severity="error",
                code="DOCUMENT_CSV_COLUMN_COUNT",
                message=f"expected {expected_columns} columns, found {len(row)}",
                source=source,
                source_locator=locator,
            )
            continue
        code = row[code_column]
        concept_id = writer.find_concept(scheme, "", code)
        if scheme == "fterm" and concept_id is None:
            base_type = _concept_type(code, None, "fterm")
            concept_id = writer.add_concept(
                scheme="fterm",
                edition="",
                code=code,
                concept_type=base_type,
                level=None,
                sequence_number=None,
                source=source,
                source_locator=locator,
                record_status="reference_only",
            )
        if normalized_text(row[text_column]) == "(Not Translated)" and concept_id is not None:
            revision_id = writer.base_revision(concept_id)
            assert revision_id is not None
            writer.add_property(
                revision_id=revision_id,
                name=f"{kind}_translation_status",
                value="not_translated",
                language=language,
                source=source,
                source_locator=locator,
            )
        writer.add_document_text(
            document_id=document_id,
            sequence_number=row_number,
            locator=f"code:{normalize_code(scheme, code)};row:{row_number}",
            heading=f"{normalize_code(scheme, code)} type {row[text_kind_column].strip()}",
            text=row[text_column],
            source_locator=locator,
        )
        writer.add_document_link(
            document_id=document_id,
            concept_id=concept_id,
            kind=kind,
            source=source,
            source_locator=locator,
        )


def _process_fi_theme(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        locator = f"row:{row_number}"
        if len(row) != 5:
            writer.add_issue(
                severity="error",
                code="FI_THEME_COLUMN_COUNT",
                message=f"expected 5 columns, found {len(row)}",
                source=source,
                source_locator=locator,
            )
            continue
        fi_id = writer.find_concept("fi", "", row[0])
        theme_id = writer.find_concept("fterm", "", row[2].strip() + row[3].strip())
        if not writer.add_relation(
            from_concept_id=fi_id,
            to_concept_id=theme_id,
            kind="fterm_theme",
            source=source,
            source_locator=locator,
        ):
            writer.add_issue(
                severity="warning",
                code="FI_THEME_TARGET_MISSING",
                message="FI or F-term theme was not found",
                source=source,
                source_locator=locator,
            )


def _process_concordance(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        locator = f"row:{row_number}"
        if len(row) != 4:
            writer.add_issue(
                severity="error",
                code="CONCORDANCE_COLUMN_COUNT",
                message=f"expected 4 columns, found {len(row)}",
                source=source,
                source_locator=locator,
            )
            continue
        left_scheme, left_edition = _concordance_target(row[0])
        right_scheme, right_edition = _concordance_target(row[2])
        left = writer.find_concept(left_scheme, left_edition, row[1])
        right = writer.find_concept(right_scheme, right_edition, row[3])
        if left is None:
            left = writer.add_concept(
                scheme=left_scheme,
                edition=left_edition,
                code=row[1],
                concept_type=_concept_type(row[1], None, left_scheme),
                level=None,
                sequence_number=None,
                source=source,
                source_locator=locator,
                record_status="reference_only",
            )
        if right is None:
            right = writer.add_concept(
                scheme=right_scheme,
                edition=right_edition,
                code=row[3],
                concept_type=_concept_type(row[3], None, right_scheme),
                level=None,
                sequence_number=None,
                source=source,
                source_locator=locator,
                record_status="reference_only",
            )
        writer.add_relation(
            from_concept_id=left,
            to_concept_id=right,
            kind="concordance",
            source=source,
            source_locator=locator,
        )


def _concordance_target(raw_version: str) -> tuple[str, str]:
    version = raw_version.strip()
    if version == "1":
        return "fi", ""
    return "ipc", "8U" if version == "8" else version


def _process_judge(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        if len(row) != 2:
            writer.add_issue(
                severity="error",
                code="JUDGE_COLUMN_COUNT",
                message=f"expected 2 columns, found {len(row)}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        writer.add_reference_entry(
            category="judge",
            key=row[0],
            language="ja",
            value=row[1],
            source=source,
            source_locator=f"row:{row_number}",
        )


def _process_xml(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    root = _parse_xml(path.read_bytes())
    title = f"FI revision {root.get('trg') or path.stem}"
    document_id = writer.add_document(
        source=source,
        kind="fi_amendment",
        language="ja",
        title=title,
        metadata={"target": root.get("trg") or path.stem},
    )
    for record_number, element in enumerate(root.findall("infor"), 1):
        locator = f"element:infor[{record_number}]"
        code = normalize_code("fi", element.findtext("FI") or "")
        translated = normalize_code("fi", element.findtext("trans") or "")
        writer.add_source_record(
            source,
            record_number,
            "xml-element",
            {
                "code": code,
                "translated": translated,
                "xml": etree.tostring(element, encoding="unicode"),
            },
        )
        text_parts = []
        for raw_value in element.itertext():
            value = cast(str, raw_value)
            if normalized_text(value):
                text_parts.append(normalized_text(value))
        writer.add_document_text(
            document_id=document_id,
            sequence_number=record_number,
            locator=f"code:{code};{locator}",
            heading=code or None,
            text="\n".join(text_parts),
            source_locator=locator,
        )
        endpoints: list[tuple[str, int]] = []
        for endpoint_role, endpoint in (("source", code), ("target", translated)):
            normalized = normalize_code("fi", endpoint)
            if not normalized:
                continue
            concept_id = writer.find_concept("fi", "", normalized)
            if concept_id is None:
                concept_id = writer.add_concept(
                    scheme="fi",
                    edition="",
                    code=normalized,
                    concept_type=_concept_type(normalized, None, "fi"),
                    level=None,
                    sequence_number=None,
                    source=source,
                    source_locator=locator,
                    record_status="reference_only",
                )
            if concept_id is None:
                writer.add_issue(
                    severity="error",
                    code="FI_AMENDMENT_ENDPOINT_UNRESOLVED",
                    message="non-empty FI amendment endpoint could not be resolved",
                    source=source,
                    source_locator=locator,
                )
                continue
            endpoints.append((normalized, concept_id))
            if endpoint_role == "source":
                writer.add_document_link(
                    document_id=document_id,
                    concept_id=concept_id,
                    kind="fi_amendment",
                    source=source,
                    source_locator=locator,
                )
        if normalize_code("fi", translated):
            source_id = next(
                (item[1] for item in endpoints if item[0] == normalize_code("fi", code)), None
            )
            target_id = next(
                (item[1] for item in endpoints if item[0] == normalize_code("fi", translated)), None
            )
            if not writer.add_relation(
                from_concept_id=source_id,
                to_concept_id=target_id,
                kind="amended_to",
                source=source,
                source_locator=locator,
            ):
                writer.add_issue(
                    severity="error",
                    code="FI_AMENDMENT_ENDPOINT_UNRESOLVED",
                    message="non-empty FI amendment relation endpoint could not be resolved",
                    source=source,
                    source_locator=locator,
                )


def _html_language(source: SourceRef) -> str:
    return "en" if source.data_group.endswith("_E") else "ja"


def _ipc_amendment_header(cells: list[str]) -> bool:
    normalized = [unicodedata.normalize("NFKC", value).strip() for value in cells]
    return normalized == ["旧IPC", "分類の発効日", "新IPC", "分類の発効日"]


def _process_html(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    parsed = parse_html(path.read_bytes())
    document_tree = parsed.root
    if parsed.recovery_used:
        writer.add_issue(
            severity="warning",
            code="HTML_RECOVERY_USED",
            message=parsed.diagnostic_summary or "HTML recovery parser reported diagnostics",
            source=source,
            source_locator="file",
        )
    title_nodes = cast(list[etree._Element], document_tree.xpath("//title"))
    title = (
        normalized_text(" ".join(cast(Iterable[str], title_nodes[0].itertext())))
        if title_nodes
        else path.stem
    )
    kind = "ipc_amendment" if source.data_group == "IPC_KAISEI" else "fterm_add_code"
    language = _html_language(source)
    document_id = writer.add_document(
        source=source,
        kind=kind,
        language="en" if language == "en" else "ja",
        title=title,
    )
    sequence = 0
    table_rows = cast(list[etree._Element], document_tree.xpath("//tr"))
    for row_number, table_row in enumerate(table_rows, 1):
        old_id: int | None = None
        new_id: int | None = None
        old_code = ""
        new_code = ""
        cell_nodes = cast(list[etree._Element], table_row.xpath("./th|./td"))
        cells = []
        for cell in cell_nodes:
            values = cast(Iterator[str], cell.itertext())
            cells.append(normalized_text(" ".join(values)))
        if not cells:
            continue
        if all(not cell for cell in cells):
            writer.add_source_record(source, row_number, "html-empty-row", cells)
            continue
        if kind == "ipc_amendment":
            if len(cells) != 4:
                if (
                    len(cell_nodes) == 1
                    and cell_nodes[0].tag.lower() == "td"
                    and cell_nodes[0].get("colspan") == "4"
                ):
                    writer.add_source_record(source, row_number, "html-retained-row", cells)
                    continue
                writer.add_source_record(source, row_number, "html-unrecognized-row", cells)
                writer.add_issue(
                    severity="error",
                    code="IPC_AMENDMENT_COLUMN_COUNT",
                    message="IPC amendment data rows must contain exactly four cells",
                    source=source,
                    source_locator=f"table-row:{row_number}",
                )
                continue
            if _ipc_amendment_header(cells) or any(node.tag.lower() == "th" for node in cell_nodes):
                writer.add_source_record(source, row_number, "html-header-row", cells)
                continue
            old_code = normalize_code("ipc", cells[0])
            new_code = normalize_code("ipc", cells[2])
            try:
                old_version = normalize_version_indicator(cells[1])
                new_version = normalize_version_indicator(cells[3])
                old_id = writer.ipc_versions.get((old_code, old_version))
                new_id = writer.ipc_versions.get((new_code, new_version))
            except ValueError:
                old_id = None
                new_id = None
            if not old_code or not new_code or old_id is None or new_id is None:
                writer.add_issue(
                    severity="error",
                    code="IPC_AMENDMENT_ENDPOINT_UNRESOLVED",
                    message="IPC amendment code and version endpoint could not be resolved",
                    source=source,
                    source_locator=f"table-row:{row_number}",
                )
                continue
        source_payload: object = cells
        if kind == "ipc_amendment":
            source_payload = {
                "from_code": old_code,
                "from_version": cells[1].strip().strip("()"),
                "to_code": new_code,
                "to_version": cells[3].strip().strip("()"),
            }
        writer.add_source_record(source, row_number, "html-table-row", source_payload)
        sequence += 1
        writer.add_document_text(
            document_id=document_id,
            sequence_number=sequence,
            locator=f"table-row:{row_number}",
            heading=cells[0] or None,
            text=" | ".join(cells),
            source_locator=f"table-row:{row_number}",
        )
        if kind == "fterm_add_code" and cells:
            theme = normalize_code("fterm", cells[0])
            if _THEME_CODE.fullmatch(theme):
                writer.add_document_link(
                    document_id=document_id,
                    concept_id=writer.find_concept("fterm", "", theme),
                    kind=kind,
                    source=source,
                    source_locator=f"table-row:{row_number}",
                )
        if kind == "ipc_amendment":
            if not writer.add_revision_relation(
                from_revision_id=old_id,
                to_revision_id=new_id,
                kind="amended_to",
                source=source,
                source_locator=f"table-row:{row_number}",
            ):
                continue
            for revision_id in (old_id, new_id):
                writer.add_document_revision_link(
                    document_id=document_id,
                    revision_id=revision_id,
                    kind=kind,
                    source=source,
                    source_locator=f"table-row:{row_number}",
                )


def _pdf_code(path: Path) -> str:
    code = path.stem.replace("_", "").replace("-", "/").rstrip("/")
    return normalize_code("ipc", code)


def _process_pdf(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    code = _pdf_code(path)
    with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
        document_id = writer.add_document(
            source=source,
            kind="ipc_definition",
            language="ja",
            title=f"IPC definition {code}",
            page_count=document.page_count,
            metadata={"code": code},
        )
        concept_id = writer.find_latest_ipc(code)
        writer.add_document_link(
            document_id=document_id,
            concept_id=concept_id,
            kind="ipc_definition",
            source=source,
            source_locator="file",
        )
        for page_number, page in enumerate(document, 1):
            text = page.get_text("text")
            if not normalized_text(text):
                writer.add_issue(
                    severity="warning",
                    code="PDF_EMPTY_PAGE",
                    message=f"no extractable text on page {page_number}",
                    source=source,
                    source_locator=f"page:{page_number}",
                )
                continue
            writer.add_document_text(
                document_id=document_id,
                sequence_number=page_number,
                locator=f"page:{page_number}",
                heading=f"{code} page {page_number}",
                text=text,
                source_locator=f"page:{page_number}",
            )


def _process_fi_amendment_links(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    for row_number, row in enumerate(_csv_rows(path), 1):
        writer.add_source_record(source, row_number, "csv-row", row)
        if len(row) < 2:
            writer.add_issue(
                severity="error",
                code="FI_AMENDMENT_LINK_COLUMN_COUNT",
                message=f"expected at least 2 columns, found {len(row)}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        code = normalize_code("fi", row[0])
        writer.add_reference_entry(
            category="fi_amendment_link",
            key=code,
            language="ja",
            value=",".join(row[1:]),
            source=source,
            source_locator=f"row:{row_number}",
        )
        relative = f"FI/FI_KAISEI_DOC/{code}.xml"
        document_id = writer.documents.get(relative)
        concept_id = writer.find_concept("fi", "", code)
        if document_id is None:
            writer.add_issue(
                severity="error",
                code="FI_AMENDMENT_LINK_TARGET_MISSING",
                message=f"amendment document not found for {code}",
                source=source,
                source_locator=f"row:{row_number}",
            )
            continue
        if concept_id is None:
            concept_id = writer.add_concept(
                scheme="fi",
                edition="",
                code=code,
                concept_type=_concept_type(code, None, "fi"),
                level=None,
                sequence_number=None,
                source=source,
                source_locator=f"row:{row_number}",
                record_status="reference_only",
            )
        writer.add_document_link(
            document_id=document_id,
            concept_id=concept_id,
            kind="fi_amendment_index",
            source=source,
            source_locator=f"row:{row_number}",
        )


def _process_copyright(writer: DatabaseWriter, source: SourceRef, path: Path) -> None:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp932")
    clean = normalized_text(text)
    if not clean:
        raise ValueError("COPYRGHT attribution must not be empty")
    writer.add_reference_entry(
        category="copyright",
        key="COPYRGHT",
        language="und",
        value=clean,
        source=source,
        source_locator="file",
    )
    writer.add_release_source(attribution=clean, source=source)


def process_sources(
    writer: DatabaseWriter, source_root: Path, entries: Iterable[SourceManifestEntry]
) -> None:
    """Process every inventoried source exactly once in dependency order."""
    ordered = tuple(entries)
    processed: set[str] = set()
    copyright_entries = [
        entry for entry in ordered if Path(entry.relative_path).name.upper() == "COPYRGHT"
    ]
    if len(copyright_entries) != 1:
        raise ValueError("source package must contain exactly one COPYRGHT file")

    def run(prefix: str, handler: object) -> None:
        for entry in ordered:
            if entry.relative_path in processed or not entry.relative_path.startswith(prefix):
                continue
            source = writer.source_for(entry)
            path = source_root / entry.relative_path
            callable_handler = handler
            assert callable(callable_handler)
            callable_handler(writer, source, path)
            processed.add(entry.relative_path)

    run("FI/FI/", _process_fi_codes)
    run("FTERM/THEME/", lambda w, s, p: _process_themes(w, s, p, "ja"))
    run("FTERM/FTERM/", lambda w, s, p: _process_fterms(w, s, p, "ja"))

    ipc_editions = {
        "IPC/IPC4_TEXT/": ("4", "ja"),
        "IPC/IPC5_TEXT/": ("5", "ja"),
        "IPC/IPC6_TEXT/": ("6", "ja"),
        "IPC/IPC7_TEXT/": ("7", "ja"),
        "IPC/IPC7E_TEXT/": ("7E", "en"),
        "IPC/IPC8B_TEXT/": ("8B", "ja"),
        "IPC/IPC8U_TEXT/": ("8U", "ja"),
    }
    for prefix, (edition, language) in ipc_editions.items():
        run(prefix, lambda w, s, p, e=edition, lang=language: _process_ipc(w, s, p, e, lang))

    run("FTERM/THEME_E/", lambda w, s, p: _process_themes(w, s, p, "en"))
    run("FTERM/FTERM_E/", lambda w, s, p: _process_fterms(w, s, p, "en"))
    run("FI/FI_TEXT/", lambda w, s, p: _process_fi_text(w, s, p, "ja"))
    run("FI/FI_TEXT_E/", lambda w, s, p: _process_fi_text(w, s, p, "en"))

    run(
        "FI/FI_HB/",
        lambda w, s, p: _process_document_csv(
            w,
            s,
            p,
            kind="fi_handbook",
            language="ja",
            expected_columns=5,
            code_column=0,
            sequence_column=1,
            text_column=4,
            text_kind_column=2,
            scheme="fi",
        ),
    )
    run(
        "FI/FI_HB_E/",
        lambda w, s, p: _process_document_csv(
            w,
            s,
            p,
            kind="fi_handbook",
            language="en",
            expected_columns=5,
            code_column=0,
            sequence_column=1,
            text_column=4,
            text_kind_column=2,
            scheme="fi",
        ),
    )
    run(
        "FTERM/FTERM_KAISETSU/",
        lambda w, s, p: _process_document_csv(
            w,
            s,
            p,
            kind="fterm_explanation",
            language="ja",
            expected_columns=4,
            code_column=0,
            sequence_column=1,
            text_column=3,
            text_kind_column=2,
            scheme="fterm",
        ),
    )
    run(
        "FTERM/FTERM_KAISETSU_E/",
        lambda w, s, p: _process_document_csv(
            w,
            s,
            p,
            kind="fterm_explanation",
            language="en",
            expected_columns=4,
            code_column=0,
            sequence_column=1,
            text_column=3,
            text_kind_column=2,
            scheme="fterm",
        ),
    )

    run(
        "FI/FI_KAISEI_DOC/",
        lambda w, s, p: None if p.suffix.lower() == ".xsl" else _process_xml(w, s, p),
    )
    run("FTERM/ADD_CODE/", _process_html)
    run("FTERM/ADD_CODE_E/", _process_html)
    run("IPC_KAISEI/", _process_html)
    run("REFERENCE/IPC_TEIGI/", _process_pdf)

    run("FI/FI_THEME/", _process_fi_theme)
    run("CONCORDANCE/", _process_concordance)
    run("FI/FI_KAISEI_LINK/", _process_fi_amendment_links)
    run("JUDGE/", _process_judge)

    for entry in ordered:
        if entry.relative_path in processed:
            continue
        source = writer.source_for(entry)
        path = source_root / entry.relative_path
        if path.name.upper() == "COPYRGHT":
            _process_copyright(writer, source, path)
            processed.add(entry.relative_path)
        elif entry.file_type == "xsl":
            processed.add(entry.relative_path)

    for entry in ordered:
        if entry.relative_path not in processed:
            writer.add_issue(
                severity="error",
                code="UNHANDLED_SOURCE",
                message=f"no adapter handled {entry.relative_path}",
                source=writer.source_for(entry),
                source_locator="file",
            )
