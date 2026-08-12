"""Shared, tolerant, network-isolated HTML parsing."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree, html


@dataclass(frozen=True, slots=True)
class ParsedHtml:
    root: etree._Element
    encoding: str
    recovery_used: bool
    diagnostic_summary: str | None


def _decode_html(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp932"), "cp932"


def parse_html(raw: bytes) -> ParsedHtml:
    """Parse PMGS HTML with recovery and return content-free diagnostics."""
    text, encoding = _decode_html(raw)
    parser = html.HTMLParser(recover=True, no_network=True)
    root = html.fromstring(text, parser=parser)
    codes = sorted({entry.type_name for entry in parser.error_log if entry.level_name != "INFO"})
    recovery_used = bool(codes)
    summary = None
    if recovery_used:
        summary = f"{len(parser.error_log)} parser diagnostic(s): {','.join(codes)}"
    return ParsedHtml(root, encoding, recovery_used, summary)
