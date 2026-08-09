"""Cross-version CSV parser limits."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from contextlib import contextmanager

# CPython 3.12 on Windows converts this setting through a signed C long.
# Keep one deterministic limit that is valid on every supported platform.
MAXIMUM_PORTABLE_CSV_FIELD_SIZE = (1 << 31) - 1


@contextmanager
def portable_csv_field_size_limit() -> Iterator[None]:
    """Temporarily raise the CSV field limit without overflowing Windows."""
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(MAXIMUM_PORTABLE_CSV_FIELD_SIZE)
        yield
    finally:
        csv.field_size_limit(previous_limit)
