"""Canonical FTS5 schema contracts shared by validation and query startup."""

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
            newline = sql.find("\n", index + 2)
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
