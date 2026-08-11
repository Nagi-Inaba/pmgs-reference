"""Shared JSON type aliases without importing the query store."""

from __future__ import annotations

type JSONValue = bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None
type JSONDict = dict[str, JSONValue]
