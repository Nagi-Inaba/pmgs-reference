"""Shared patent-classification code normalization rules."""

from __future__ import annotations

import re
from typing import Literal

Scheme = Literal["fi", "fterm", "ipc"]
SUPPORTED_SCHEMES: frozenset[str] = frozenset({"fi", "fterm", "ipc"})


def normalize_code(scheme: str, code: str) -> str:
    """Normalize only spacing and ASCII letter case while preserving punctuation."""
    normalized_scheme = scheme.strip().lower()
    if normalized_scheme not in SUPPORTED_SCHEMES:
        raise ValueError(f"unsupported scheme: {scheme}")
    return re.sub(r"\s+", "", code or "").upper()


def group_key(scheme: str, normalized_code: str) -> str:
    """Return the stable public grouping key for an already-normalized code."""
    normalized_scheme = scheme.strip().lower()
    if normalized_scheme not in SUPPORTED_SCHEMES:
        raise ValueError(f"unsupported scheme: {scheme}")
    if normalized_scheme == "fterm":
        return normalized_code[:5]
    if "/" in normalized_code:
        return normalized_code.split("/", maxsplit=1)[0]
    return normalized_code
