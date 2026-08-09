from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmgs_reference.normalization import group_key, normalize_code

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("scheme", "raw", "expected"),
    [
        ("fi", " G06F   3/  048 ", "G06F3/048"),
        ("ipc", " g06f 3/048 ", "G06F3/048"),
        ("fterm", "4C083 AA01", "4C083AA01"),
    ],
)
def test_normalize_code(scheme: str, raw: str, expected: str) -> None:
    assert normalize_code(scheme, raw) == expected


def test_all_shared_vectors() -> None:
    payload = json.loads(
        (ROOT / "schemas" / "normalization-vectors.json").read_text(encoding="utf-8")
    )
    for vector in payload["vectors"]:
        normalized = normalize_code(vector["scheme"], vector["input"])
        assert normalized == vector["normalized"]
        assert group_key(vector["scheme"], normalized) == vector["group_key"]


def test_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported scheme"):
        normalize_code("cpc", "G06F3/048")
