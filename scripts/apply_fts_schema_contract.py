from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label} anchor mismatch: {text.count(old)}")
    return text.replace(old, new, 1)


def replace_block(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    end_index = text.find(end, start_index + len(start))
    if start_index < 0 or end_index < 0:
        raise SystemExit(f"{label} block anchor mismatch")
    return text[:start_index] + replacement + text[end_index:]


def write_contract_module() -> None:
    Path("src/pmgs_reference/fts_schema.py").write_text(
        '''"""Canonical FTS5 schema contracts shared by validation and query startup."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FTS5SchemaContract:
    """One exact virtual-table contract without exposing source DDL."""

    table: str
    columns: tuple[tuple[str, bool], ...]
    tokenizer: str


CANONICAL_FTS5_SCHEMAS: dict[str, FTS5SchemaContract] = {
    "concept_text_fts": FTS5SchemaContract(
        table="concept_text_fts",
        columns=(
            ("text", False),
            ("revision_id", True),
            ("language", True),
            ("kind", True),
        ),
        tokenizer="trigram",
    ),
    "document_text_fts": FTS5SchemaContract(
        table="document_text_fts",
        columns=(
            ("text", False),
            ("document_id", True),
            ("sequence_number", True),
        ),
        tokenizer="trigram",
    ),
}

_CANONICAL_STATUS = "canonical_fts5_schema"


def _sql_tokens(sql: str) -> list[tuple[str, str]]:
    """Tokenize the bounded SQLite DDL subset needed for FTS5 contracts."""
    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                return []
            index = end + 2
            continue
        if character == "'":
            index += 1
            value: list[str] = []
            closed = False
            while index < length:
                if sql[index] == "'":
                    if index + 1 < length and sql[index + 1] == "'":
                        value.append("'")
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                value.append(sql[index])
                index += 1
            if not closed:
                return []
            tokens.append(("string", "".join(value).casefold()))
            continue
        if character in {'"', "`", "["}:
            closing = "]" if character == "[" else character
            index += 1
            value = []
            closed = False
            while index < length:
                if sql[index] == closing:
                    if index + 1 < length and sql[index + 1] == closing:
                        value.append(closing)
                        index += 2
                        continue
                    index += 1
                    closed = True
                    break
                value.append(sql[index])
                index += 1
            if not closed:
                return []
            tokens.append(("identifier", "".join(value).casefold()))
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append(("word", sql[index:end].casefold()))
            index = end
            continue
        tokens.append(("symbol", character))
        index += 1
    return tokens


def _virtual_table_definition(sql: str) -> tuple[str, list[tuple[str, str]]] | None:
    tokens = _sql_tokens(sql)
    position = 0

    def take_word(value: str) -> bool:
        nonlocal position
        if position >= len(tokens) or tokens[position] != ("word", value):
            return False
        position += 1
        return True

    if not take_word("create"):
        return None
    if position < len(tokens) and tokens[position] in {
        ("word", "temp"),
        ("word", "temporary"),
    }:
        position += 1
    if not take_word("virtual") or not take_word("table"):
        return None
    if position + 2 < len(tokens) and tokens[position : position + 3] == [
        ("word", "if"),
        ("word", "not"),
        ("word", "exists"),
    ]:
        position += 3
    if position >= len(tokens) or tokens[position][0] not in {"word", "identifier"}:
        return None
    position += 1
    if position + 1 < len(tokens) and tokens[position] == ("symbol", "."):
        if tokens[position + 1][0] not in {"word", "identifier"}:
            return None
        position += 2
    if not take_word("using"):
        return None
    if position >= len(tokens) or tokens[position][0] not in {"word", "identifier"}:
        return None
    module = tokens[position][1]
    position += 1
    if position >= len(tokens) or tokens[position] != ("symbol", "("):
        return None
    position += 1
    arguments: list[tuple[str, str]] = []
    depth = 1
    while position < len(tokens):
        token = tokens[position]
        position += 1
        if token == ("symbol", "("):
            depth += 1
        elif token == ("symbol", ")"):
            depth -= 1
            if depth == 0:
                return module, arguments
        arguments.append(token)
    return None


def virtual_table_module(sql: str) -> str | None:
    """Return the actual module token, ignoring comments and quoted names."""
    definition = _virtual_table_definition(sql)
    return definition[0] if definition is not None else None


def _split_arguments(tokens: list[tuple[str, str]]) -> list[list[tuple[str, str]]] | None:
    arguments: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    depth = 0
    for token in tokens:
        if token == ("symbol", "("):
            depth += 1
        elif token == ("symbol", ")"):
            if depth == 0:
                return None
            depth -= 1
        if token == ("symbol", ",") and depth == 0:
            if not current:
                return None
            arguments.append(current)
            current = []
        else:
            current.append(token)
    if depth != 0 or not current:
        return None
    arguments.append(current)
    return arguments


def schema_status(sql: str | None, contract: FTS5SchemaContract) -> str:
    """Return a stable, sanitized status for one canonical FTS5 table."""
    if sql is None:
        return "missing"
    definition = _virtual_table_definition(sql)
    if definition is None or definition[0] != "fts5":
        return "not_fts5"
    arguments = _split_arguments(definition[1])
    if arguments is None:
        return "invalid_schema"

    columns: list[tuple[str, bool]] = []
    tokenizer_values: list[str] = []
    extra_options = False
    for argument in arguments:
        if not argument or argument[0][0] not in {"word", "identifier"}:
            return "invalid_schema"
        name = argument[0][1]
        if len(argument) >= 2 and argument[1] == ("symbol", "="):
            if len(argument) != 3 or argument[2][0] not in {"word", "identifier", "string"}:
                return "invalid_schema"
            if name == "tokenize":
                tokenizer_values.append(argument[2][1].strip().casefold())
            else:
                extra_options = True
            continue
        remainder = argument[1:]
        if not remainder:
            columns.append((name, False))
        elif remainder == [("word", "unindexed")]:
            columns.append((name, True))
        else:
            return "invalid_schema"

    expected_names = tuple(name for name, _ in contract.columns)
    actual_names = tuple(name for name, _ in columns)
    if actual_names != expected_names:
        return "columns_mismatch"
    expected_unindexed = tuple(unindexed for _, unindexed in contract.columns)
    actual_unindexed = tuple(unindexed for _, unindexed in columns)
    if actual_unindexed != expected_unindexed:
        return "unindexed_mismatch"
    if tokenizer_values != [contract.tokenizer.casefold()]:
        return "tokenizer_mismatch"
    if extra_options:
        return "options_mismatch"
    return _CANONICAL_STATUS


def inspect_fts5_schemas(connection: sqlite3.Connection) -> dict[str, str]:
    """Inspect every canonical table without returning source SQL."""
    tables = tuple(CANONICAL_FTS5_SCHEMAS)
    placeholders = ", ".join("?" for _ in tables)
    rows = {
        str(row[0]): str(row[1]) if row[1] is not None else None
        for row in connection.execute(
            f"SELECT name, sql FROM sqlite_schema WHERE type = 'table' "
            f"AND name IN ({placeholders})",
            tables,
        )
    }
    return {
        table: schema_status(rows.get(table), contract)
        for table, contract in CANONICAL_FTS5_SCHEMAS.items()
    }
''',
        encoding="utf-8",
    )


def patch_validation() -> None:
    path = Path("src/pmgs_reference/validation.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from pathlib import Path\n\nfrom pmgs_reference.validation_core import (\n",
        "from pathlib import Path\n\nfrom pmgs_reference.fts_schema import (\n"
        "    CANONICAL_FTS5_SCHEMAS,\n"
        "    inspect_fts5_schemas,\n"
        "    virtual_table_module,\n"
        ")\n"
        "from pmgs_reference.validation_core import (\n",
        "validation imports",
    )
    text = replace_once(
        text,
        '_FTS_TABLES = ("concept_text_fts", "document_text_fts")\n',
        "_FTS_TABLES = tuple(CANONICAL_FTS5_SCHEMAS)\n"
        '_CANONICAL_FTS5_SCHEMA = "canonical_fts5_schema"\n',
        "validation table constants",
    )
    replacement = '''def _virtual_table_module(sql: str) -> str | None:
    """Compatibility wrapper for the comment-safe shared DDL parser."""
    return virtual_table_module(sql)


def _fts5_table_statuses(connection: sqlite3.Connection) -> dict[str, str]:
    return inspect_fts5_schemas(connection)


def _fts5_schema_checks_from_statuses(
    statuses: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        f"{table}_schema": _check(
            _CANONICAL_FTS5_SCHEMA,
            status,
            status == _CANONICAL_FTS5_SCHEMA,
        )
        for table, status in statuses.items()
    }


'''
    text = replace_block(
        text,
        "def _sql_tokens(sql: str) -> list[tuple[str, str]]:\n",
        "def _schema_failure_results(statuses: dict[str, str]) -> dict[str, dict[str, object]]:\n",
        replacement,
        "validation parser",
    )
    text = text.replace('status == "fts5"', 'status == _CANONICAL_FTS5_SCHEMA')
    text = text.replace(
        'all(status == "fts5" for status in statuses.values())',
        "all(status == _CANONICAL_FTS5_SCHEMA for status in statuses.values())",
    )
    source_anchor = """def _source_schema_failures(
    database_path: Path,
) -> dict[str, dict[str, object]] | None:
"""
    schema_reader = '''def _fts5_schema_checks(database_path: Path) -> dict[str, dict[str, object]]:
    path = database_path.resolve()
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        actual = f"database_error:{type(exc).__name__}"
        return {
            f"{table}_schema": _check(_CANONICAL_FTS5_SCHEMA, actual, False)
            for table in _FTS_TABLES
        }
    try:
        statuses = _fts5_table_statuses(connection)
    except sqlite3.DatabaseError as exc:
        actual = f"database_error:{type(exc).__name__}"
        return {
            f"{table}_schema": _check(_CANONICAL_FTS5_SCHEMA, actual, False)
            for table in _FTS_TABLES
        }
    finally:
        connection.close()
    return _fts5_schema_checks_from_statuses(statuses)


'''
    text = replace_once(text, source_anchor, schema_reader + source_anchor, "schema reader")
    old_validate = '''def validate_database(database_path: Path) -> ValidationResult:
    """Run the existing validator and add a read-only FTS5 inverted-index gate."""
    result = _validate_core_database(database_path)
    fts_checks = _fts5_checks(database_path, result.integrity_check)
    checks = dict(result.checks)
    checks.update(fts_checks)
    fts_valid = all(bool(check.get("match")) for check in fts_checks.values())
    return replace(result, valid=result.valid and fts_valid, checks=checks)
'''
    new_validate = '''def validate_database(database_path: Path) -> ValidationResult:
    """Run the existing validator and add canonical FTS5 schema and integrity gates."""
    result = _validate_core_database(database_path)
    schema_checks = _fts5_schema_checks(database_path)
    integrity_checks = _fts5_checks(database_path, result.integrity_check)
    checks = dict(result.checks)
    checks.update(schema_checks)
    checks.update(integrity_checks)
    fts_checks = {**schema_checks, **integrity_checks}
    fts_valid = all(bool(check.get("match")) for check in fts_checks.values())
    return replace(result, valid=result.valid and fts_valid, checks=checks)
'''
    text = replace_once(text, old_validate, new_validate, "validation entrypoint")
    path.write_text(text, encoding="utf-8")


def patch_store() -> None:
    path = Path("src/pmgs_reference/store.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from pmgs_reference.errors import (\n",
        "from pmgs_reference.fts_schema import CANONICAL_FTS5_SCHEMAS, inspect_fts5_schemas\n"
        "from pmgs_reference.errors import (\n",
        "store imports",
    )
    old_query = '''            fts_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'concept_text_fts'"
            ).fetchone()
'''
    text = replace_once(
        text,
        old_query,
        "            fts_statuses = inspect_fts5_schemas(connection)\n",
        "store schema query",
    )
    old_result = '''        if fts_row is None:
            raise ValueError("PMGS Reference search index is missing")
        fts_sql = str(fts_row[0]).lower()
        tokenizer = "trigram" if "tokenize = 'trigram'" in fts_sql else "legacy"
        return cls(resolved, tokenizer)
'''
    new_result = '''        for table, status in fts_statuses.items():
            if status != "canonical_fts5_schema":
                raise ValueError(
                    f"PMGS Reference search index schema is invalid: {table} ({status})"
                )
        tokenizers = {contract.tokenizer for contract in CANONICAL_FTS5_SCHEMAS.values()}
        if len(tokenizers) != 1:
            raise RuntimeError("canonical FTS5 tokenizer contract is inconsistent")
        return cls(resolved, tokenizers.pop())
'''
    text = replace_once(text, old_result, new_result, "store schema result")
    path.write_text(text, encoding="utf-8")


def write_verification() -> None:
    Path("docs/verification/fts5-schema-contract-2026-08-23.md").write_text(
        '''# Canonical FTS5 schema contract — 2026-08-23

Issue #57 / PR #61

## Contract

The canonical query database contains two FTS5 virtual tables. Validation and `PMGSStore.open()` consume the same code-defined contract for both tables.

- `concept_text_fts`: `text`, `revision_id UNINDEXED`, `language UNINDEXED`, `kind UNINDEXED`
- `document_text_fts`: `text`, `document_id UNINDEXED`, `sequence_number UNINDEXED`
- both tables use exactly the `trigram` tokenizer

Column order, `UNINDEXED` flags, tokenizer, unexpected columns, and additional options are fail-closed. Public validation checks expose only stable statuses such as `columns_mismatch`, `unindexed_mismatch`, and `tokenizer_mismatch`; they do not expose SQLite DDL or local paths.

## TDD evidence

The initial RED commit demonstrated that the previous validator accepted missing `UNINDEXED` declarations, reordered or extra columns, and a document index using `unicode61`. It also showed that `PMGSStore.open()` inspected only the concept-table tokenizer and accepted a document-table mismatch.

The implementation introduces one shared parser and contract module, adds two stable validation checks, and makes Store startup reject a mismatch in either table before serving queries. Existing read-only FTS5 posting-integrity checks remain separate and continue to run after the schema gate.

A fresh hosted CI matrix is required before merge.
''',
        encoding="utf-8",
    )


def apply() -> None:
    write_contract_module()
    patch_validation()
    patch_store()
    write_verification()


if __name__ == "__main__":
    apply()
