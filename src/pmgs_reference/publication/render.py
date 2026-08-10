"""Server-rendered HTML, Markdown, discovery, and OpenAPI artifacts."""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from pmgs_reference.publication.model import GroupSpec
from pmgs_reference.publication.policy import SourcePresentation


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _mapping_items(record: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = record.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _scheme_name(scheme: str) -> str:
    return {"fi": "FI", "fterm": "F-term", "ipc": "IPC"}.get(scheme, scheme)


def _localized(language: str, *, ja: str, en: str) -> str:
    return en if language == "en" else ja


def _source_notice_html(source: SourcePresentation, language: str) -> str:
    heading = _localized(language, ja="出典と加工について", en="Source and processing")
    source_label = _localized(language, ja="原典案内", en="JPO source")
    processing_label = _localized(language, ja="加工表示", en="Processing notice")
    service_label = _localized(language, ja="運営主体", en="Service status")
    return f"""<section class="source-notice" aria-label="{_text(heading)}">
  <h2>{_text(heading)}</h2>
  <p><strong>{_text(source_label)}:</strong>
    <a href="{_text(source.source_url)}">{_text(source.owner)}</a>
  </p>
  <p><strong>Attribution:</strong> {_text(source.attribution)}</p>
  <p><strong>{_text(processing_label)}:</strong> {_text(source.processing_notice(language))}</p>
  <p><strong>{_text(service_label)}:</strong> {_text(source.non_affiliation_notice(language))}</p>
</section>"""


def _source_notice_markdown(source: SourcePresentation, language: str) -> list[str]:
    heading = _localized(language, ja="出典と加工について", en="Source and processing")
    source_label = _localized(language, ja="原典案内", en="JPO source")
    processing_label = _localized(language, ja="加工表示", en="Processing notice")
    service_label = _localized(language, ja="運営主体", en="Service status")
    return [
        f"## {heading}",
        "",
        f"- {source_label}: [{source.owner}]({source.source_url})",
        f"- Attribution: {source.attribution}",
        f"- {processing_label}: {source.processing_notice(language)}",
        f"- {service_label}: {source.non_affiliation_notice(language)}",
        "",
    ]


def _page_navigation(previous_url: str | None, next_url: str | None) -> str:
    links: list[str] = []
    if previous_url:
        links.append(f'<a rel="prev" href="{_text(previous_url)}">Previous</a>')
    if next_url:
        links.append(f'<a rel="next" href="{_text(next_url)}">Next</a>')
    return f'<nav aria-label="Pagination">{" · ".join(links)}</nav>' if links else ""


def _source_list(record: Mapping[str, Any]) -> str:
    sources = _mapping_items(record, "sources")
    if not sources:
        return "<p>Source metadata unavailable.</p>"
    items = "".join(
        "<li>"
        f"{_text(source.get('title', ''))} — {_text(source.get('relative_id', ''))} "
        f"<code>{_text(source.get('sha256', ''))}</code>"
        "</li>"
        for source in sources
    )
    return f"<ul>{items}</ul>"


def _classification_article(record: Mapping[str, Any], base_url: str) -> str:
    scheme = str(record["scheme"])
    code = str(record["code"])
    edition = record.get("edition")
    fragment = str(record["fragment"])
    labels = _mapping_items(record, "labels")
    texts = _mapping_items(record, "texts")
    properties = _mapping_items(record, "properties")
    relations = _mapping_items(record, "relations")
    documents = _mapping_items(record, "documents")
    display_label = str(labels[0].get("text", "")) if labels else "JPO-provided label unavailable"

    text_html = (
        "".join(
            f'<section class="official-text"><h4>{_text(item.get("kind", "text"))}</h4>'
            f"<p>{_text(item.get('text', ''))}</p>"
            f'<p class="source-ref">{_text(item.get("source_id", ""))} '
            f"{_text(item.get('locator', ''))}</p></section>"
            for item in texts
        )
        or "<p>JPO-provided explanatory text is not available in this language.</p>"
    )
    property_html = "".join(
        f"<li><code>{_text(item.get('name', ''))}</code>: {_text(item.get('value', ''))}</li>"
        for item in properties
    )
    relation_html = "".join(
        f"<li>{_text(item.get('type', 'related'))}: "
        f"{_text(_scheme_name(str(item.get('scheme', ''))))} "
        f"<code>{_text(item.get('code', ''))}</code>"
        f"{f' ({_text(item.get("edition"))})' if item.get('edition') else ''}</li>"
        for item in relations
    )
    document_html = "".join(
        f'<li><a href="/{_text(record.get("language", "ja"))}/documents/'
        f'{_text(item.get("document_id", ""))}">{_text(item.get("title", ""))}</a> '
        f"({_text(item.get('kind', ''))})</li>"
        for item in documents
    )
    query = urlencode(
        {
            "scheme": scheme,
            "code": code,
            "release": str(record["release_id"]),
            "language": str(record["language"]),
            **({"edition": str(edition)} if edition else {}),
        }
    )
    return f"""
<article id="{_text(fragment)}" class="classification-record">
  <header>
    <p class="eyebrow">{_text(_scheme_name(scheme))}{f" · {_text(edition)}" if edition else ""}</p>
    <h2><code>{_text(code)}</code></h2>
    <p>{_text(display_label)}</p>
  </header>
  <h3>JPO-provided text</h3>
  {text_html}
  {f"<h3>Properties</h3><ul>{property_html}</ul>" if property_html else ""}
  {f"<h3>Hierarchy and mappings</h3><ul>{relation_html}</ul>" if relation_html else ""}
  {f"<h3>Related JPO-provided documents</h3><ul>{document_html}</ul>" if document_html else ""}
  <h3>Sources</h3>
  {_source_list(record)}
  <p><a href="{_text(base_url)}/api/v1/lookup?{_text(query)}">JSON API</a></p>
</article>"""


def classification_html(
    *,
    spec: GroupSpec,
    language: str,
    records: Sequence[Mapping[str, Any]],
    page_url: str,
    previous_url: str | None,
    next_url: str | None,
    release_id: str,
    base_url: str,
    source: SourcePresentation,
) -> str:
    """Render a classification group chunk with no client-side dependency."""
    title = f"{_scheme_name(spec.kind)} {spec.group_key} — PMGS Reference"
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "itemListElement": [
            {
                "@type": "DefinedTerm",
                "position": index,
                "termCode": str(record["code"]),
                "name": (
                    str(_mapping_items(record, "labels")[0].get("text", record["code"]))
                    if _mapping_items(record, "labels")
                    else str(record["code"])
                ),
                "url": str(record["canonical_url"]),
                "inDefinedTermSet": f"PMGS {release_id}",
            }
            for index, record in enumerate(records, 1)
        ],
    }
    json_ld = json.dumps(item_list, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    articles = "\n".join(_classification_article(record, base_url) for record in records)
    navigation = _page_navigation(previous_url, next_url)
    description = _localized(
        language,
        ja="特許庁提供のPMGS分類データです。AI要約や法的解釈は追加していません。",
        en="JPO-provided PMGS classification data without AI summary or legal interpretation.",
    )
    return f"""<!doctype html>
<html lang="{_text(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_text(title)}</title>
  <link rel="canonical" href="{_text(page_url)}">
  <link rel="stylesheet" href="/assets/style.css">
  <script type="application/ld+json">{json_ld}</script>
  <script src="/assets/webmcp.js" defer></script>
</head>
<body>
<main>
  <header class="page-header">
    <p class="eyebrow">PMGS Reference · {_text(release_id)}</p>
    <h1>{_text(_scheme_name(spec.kind))} <code>{_text(spec.group_key)}</code></h1>
    <p>{_text(description)}</p>
  </header>
  {_source_notice_html(source, language)}
  {navigation}
  {articles}
  {navigation}
</main>
</body>
</html>
"""


def classification_markdown(
    *,
    spec: GroupSpec,
    language: str,
    records: Sequence[Mapping[str, Any]],
    page_url: str,
    previous_url: str | None,
    next_url: str | None,
    release_id: str,
    source: SourcePresentation,
) -> str:
    """Render the same classification chunk as agent-readable Markdown."""
    lines = [
        "---",
        f"title: {json.dumps(f'{_scheme_name(spec.kind)} {spec.group_key}', ensure_ascii=False)}",
        f"language: {language}",
        f"release_id: {release_id}",
        f"canonical_url: {json.dumps(page_url)}",
        "provenance: official",
        "---",
        "",
        f"# {_scheme_name(spec.kind)} `{spec.group_key}`",
        "",
        _localized(
            language,
            ja="特許庁提供のPMGS分類データです。AI要約や法的解釈は追加していません。",
            en="JPO-provided PMGS classification data without AI summary or legal interpretation.",
        ),
        "",
    ]
    lines.extend(_source_notice_markdown(source, language))
    if previous_url or next_url:
        navigation = []
        if previous_url:
            navigation.append(f"[Previous]({previous_url})")
        if next_url:
            navigation.append(f"[Next]({next_url})")
        lines.extend([" · ".join(navigation), ""])
    for record in records:
        lines.extend(
            [
                f"## {_scheme_name(str(record['scheme']))} `{record['code']}`",
                "",
                f"- Canonical: {record['canonical_url']}",
                f"- Edition: {record.get('edition') or 'current'}",
                f"- Fragment: `{record['fragment']}`",
                "",
            ]
        )
        labels = _mapping_items(record, "labels")
        if labels:
            lines.extend([str(item.get("text", "")) for item in labels] + [""])
        for item in _mapping_items(record, "texts"):
            lines.extend(
                [
                    f"### {item.get('kind', 'official_text')}",
                    "",
                    str(item.get("text", "")),
                    "",
                    f"Source: `{item.get('source_id', '')}` `{item.get('locator', '')}`",
                    "",
                ]
            )
        properties = _mapping_items(record, "properties")
        if properties:
            lines.extend(["### Properties", ""])
            lines.extend(
                f"- `{item.get('name', '')}`: {item.get('value', '')}" for item in properties
            )
            lines.append("")
        relations = _mapping_items(record, "relations")
        if relations:
            lines.extend(["### Hierarchy and mappings", ""])
            lines.extend(
                f"- {item.get('type', '')}: {item.get('scheme', '')} "
                f"`{item.get('code', '')}` {item.get('edition') or ''}"
                for item in relations
            )
            lines.append("")
        documents = _mapping_items(record, "documents")
        if documents:
            lines.extend(["### Related JPO-provided documents", ""])
            lines.extend(
                f"- `{item.get('document_id', '')}` {item.get('title', '')} "
                f"({item.get('kind', '')})"
                for item in documents
            )
            lines.append("")
        lines.extend(["### Sources", ""])
        lines.extend(
            f"- {item.get('relative_id', '')} — `{item.get('sha256', '')}`"
            for item in _mapping_items(record, "sources")
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def document_html(
    *,
    manifest: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    page_url: str,
    previous_url: str | None,
    next_url: str | None,
    source: SourcePresentation,
) -> str:
    title = str(manifest["title"])
    navigation = _page_navigation(previous_url, next_url)
    language = str(manifest["site_language"])
    description = _localized(
        language,
        ja="特許庁提供文書の抽出本文",
        en="Extracted text from a JPO-provided document",
    )
    sections = (
        "\n".join(
            f'<section id="segment-{int(segment["sequence_number"])}">'
            f"<h2>{_text(segment.get('heading') or segment.get('locator') or 'Section')}</h2>"
            f"<p>{_text(segment.get('text', ''))}</p>"
            f'<p class="source-ref">{_text(segment.get("source_locator", ""))}</p></section>'
            for segment in segments
        )
        or "<p>No extractable JPO-provided text is present in this document.</p>"
    )
    return f"""<!doctype html>
<html lang="{_text(manifest["site_language"])}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_text(title)} — PMGS Reference</title>
  <link rel="canonical" href="{_text(page_url)}">
  <link rel="stylesheet" href="/assets/style.css">
  <script src="/assets/webmcp.js" defer></script>
</head>
<body><main>
  <header class="page-header">
    <p class="eyebrow">PMGS Reference · {_text(manifest["release_id"])}</p>
    <h1>{_text(title)}</h1>
    <p>{_text(manifest["kind"])} · {_text(description)}</p>
  </header>
  {_source_notice_html(source, language)}
  {navigation}
  {sections}
  {navigation}
  <h2>Source</h2>
  <p>{_text(manifest["source"]["relative_id"])}</p>
  <p><code>{_text(manifest["source"]["sha256"])}</code></p>
  <p><a href="{_text(manifest["source"]["original_url"])}">
    {_text(manifest["source"]["owner"])}
  </a></p>
  <p>{_text(manifest["source"]["attribution"])}</p>
</main></body>
</html>
"""


def document_markdown(
    *,
    manifest: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    page_url: str,
    previous_url: str | None,
    next_url: str | None,
    source: SourcePresentation,
) -> str:
    lines = [
        "---",
        f"title: {json.dumps(str(manifest['title']), ensure_ascii=False)}",
        f"language: {manifest['site_language']}",
        f"release_id: {manifest['release_id']}",
        f"document_id: {manifest['document_id']}",
        f"canonical_url: {json.dumps(page_url)}",
        "provenance: official",
        "---",
        "",
        f"# {manifest['title']}",
        "",
        _localized(
            str(manifest["site_language"]),
            ja=f"特許庁提供文書の種別: `{manifest['kind']}`。",
            en=f"JPO-provided document type: `{manifest['kind']}`.",
        ),
        "",
    ]
    lines.extend(_source_notice_markdown(source, str(manifest["site_language"])))
    if previous_url:
        lines.append(f"[Previous]({previous_url})")
    if next_url:
        lines.append(f"[Next]({next_url})")
    if previous_url or next_url:
        lines.append("")
    for segment in segments:
        heading = segment.get("heading") or segment.get("locator") or "Section"
        lines.extend(
            [
                f"## {heading}",
                "",
                str(segment.get("text", "")),
                "",
                f"Source locator: `{segment.get('source_locator', '')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Source",
            "",
            f"- {manifest['source']['relative_id']}",
            f"- Owner: {manifest['source']['owner']}",
            f"- JPO source: {manifest['source']['original_url']}",
            f"- Attribution: {manifest['source']['attribution']}",
            f"- SHA-256: `{manifest['source']['sha256']}`",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def home_html(
    base_url: str,
    release_id: str,
    source: SourcePresentation,
    language: str = "ja",
) -> str:
    is_english = language == "en"
    canonical = f"{base_url}/en/" if is_english else f"{base_url}/"
    alternate = f"{base_url}/" if is_english else f"{base_url}/en/"
    switch_label = "日本語" if is_english else "English"
    introduction = _localized(
        language,
        ja="特許庁が提供するPMGSデータに含まれる分類本文を、版と出典を保って参照するための独立した情報提供サービスです。",
        en=(
            "An independent reference service for JPO-provided PMGS classification text "
            "with release and source lineage."
        ),
    )
    scheme_label = _localized(language, ja="分類体系", en="Scheme")
    code_label = _localized(language, ja="分類コード", en="Code")
    lookup_label = _localized(language, ja="完全一致で照会", en="Exact lookup")
    access_heading = _localized(language, ja="機械可読の入口", en="Machine-readable access")
    coverage_label = _localized(language, ja="公開範囲", en="Coverage")
    sitemap_label = _localized(language, ja="サイトマップ", en="Sitemap")
    boundary = _localized(
        language,
        ja="本サービスはJPO提供本文を表示し、AI要約、分類推測、法的判断を追加しません。",
        en=(
            "This service displays JPO-provided text without AI summaries, "
            "classification predictions, or legal conclusions."
        ),
    )
    return f"""<!doctype html>
<html lang="{_text(language)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PMGS Reference</title>
<link rel="canonical" href="{_text(canonical)}">
<link rel="alternate" hreflang="ja" href="{_text(base_url)}/">
<link rel="alternate" hreflang="en" href="{_text(base_url)}/en/">
<link rel="stylesheet" href="/assets/style.css">
<script src="/assets/webmcp.js" defer></script></head>
<body><main><header class="page-header">
<nav><a href="{_text(alternate)}" hreflang="{"ja" if is_english else "en"}">{switch_label}</a></nav>
<p class="eyebrow">Release {_text(release_id)}</p><h1>PMGS Reference</h1>
<p>{introduction}</p></header>
{_source_notice_html(source, language)}
<form action="/api/v1/lookup" method="get">
<label>{scheme_label} <select name="scheme"><option>fi</option><option>fterm</option>
<option>ipc</option></select></label>
<label>{code_label} <input name="code" required maxlength="128"></label>
<input type="hidden" name="language" value="{_text(language)}">
<button>{lookup_label}</button></form>
<h2>{access_heading}</h2><ul>
<li><a href="/openapi.json">OpenAPI 3.1</a></li>
<li><a href="/{"llms.en.txt" if is_english else "llms.txt"}">llms.txt</a></li>
<li><a href="/api/v1/coverage">{coverage_label}</a></li>
<li><a href="/sitemap.xml">{sitemap_label}</a></li></ul>
<p>{boundary}</p></main></body></html>
"""


def stylesheet() -> str:
    return (
        "*{box-sizing:border-box}"
        "body{margin:0;background:#f7f6f2;color:#172126;"
        "font:16px/1.65 system-ui,-apple-system,sans-serif}"
        "main{max-width:980px;margin:auto;padding:2rem 1.25rem 5rem}"
        "a{color:#075f63}code{overflow-wrap:anywhere}"
        ".page-header{padding:1.5rem 0;border-bottom:3px solid #173d3f}"
        ".eyebrow{font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#526568}"
        ".classification-record,.official-text,section{margin:1.5rem 0;padding:1rem;"
        "background:#fff;border:1px solid #d7ddda;border-radius:.4rem}"
        ".source-ref{font-size:.85rem;color:#526568}nav{margin:1.25rem 0}"
        "label{display:block;margin:.75rem 0}input,select,button{font:inherit;padding:.45rem}"
        "button{background:#173d3f;color:#fff;border:0;border-radius:.25rem;"
        "padding:.55rem 1rem}"
        "@media(max-width:600px){main{padding:1rem}.classification-record{padding:.8rem}}"
    )


def llms_text(
    base_url: str,
    release_id: str,
    source: SourcePresentation,
    language: str = "ja",
) -> str:
    if language == "en":
        return f"""# PMGS Reference

Release: {release_id}

This independent site exposes JPO-provided PMGS classification text with source lineage.
It does not provide AI summaries, semantic search, classification predictions, or legal advice.

Attribution: {source.attribution}
JPO source: {source.source_url}
Processing notice: {source.processing_notice_en}
Service status: {source.non_affiliation_notice_en}

- Exact lookup API: {base_url}/api/v1/lookup
- OpenAPI 3.1: {base_url}/openapi.json
- Coverage: {base_url}/api/v1/coverage
- Sitemap: {base_url}/sitemap.xml
- Release manifest: {base_url}/releases/{release_id}/manifest.json

Use scheme, code, release, edition, and language explicitly. Cite the returned release_id,
official text, source relative_id, source SHA-256, and canonical_url.
"""
    return f"""# PMGS Reference

リリース: {release_id}

この独立したサイトは、特許庁提供のPMGS分類本文を出典情報とともに公開します。
AI要約、意味検索、分類推測、法的助言は提供しません。

帰属表示: {source.attribution}
特許庁の原典案内: {source.source_url}
加工表示: {source.processing_notice_ja}
運営主体: {source.non_affiliation_notice_ja}

- 完全一致API: {base_url}/api/v1/lookup
- OpenAPI 3.1: {base_url}/openapi.json
- 公開範囲: {base_url}/api/v1/coverage
- サイトマップ: {base_url}/sitemap.xml
- リリースmanifest: {base_url}/releases/{release_id}/manifest.json
- English: {base_url}/llms.en.txt

scheme、code、release、edition、languageを明示してください。回答ではrelease_id、
公式文言、source relative_id、source SHA-256、canonical_urlを出典として示してください。
"""


def robots_text(base_url: str) -> str:
    return (
        "User-agent: *\n"
        "Content-Signal: search=yes, ai-input=yes, ai-train=no\n"
        "Allow: /\n\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )


def sitemap_documents(
    base_url: str, urls: Iterable[str], shard_size: int = 45_000
) -> dict[str, str]:
    """Return one sitemap or a sitemap index plus deterministic shards."""
    unique = sorted(set(urls))
    shards = [unique[index : index + shard_size] for index in range(0, len(unique), shard_size)]
    if len(shards) <= 1:
        entries = "".join(f"<url><loc>{_text(url)}</loc></url>" for url in unique)
        return {
            "sitemap.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"{entries}</urlset>"
            )
        }
    output: dict[str, str] = {}
    index_entries: list[str] = []
    for number, shard in enumerate(shards, 1):
        key = f"sitemaps/sitemap-{number:03d}.xml"
        entries = "".join(f"<url><loc>{_text(url)}</loc></url>" for url in shard)
        output[key] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{entries}</urlset>"
        )
        index_entries.append(f"<sitemap><loc>{_text(base_url)}/{key}</loc></sitemap>")
    output["sitemap.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{''.join(index_entries)}</sitemapindex>"
    )
    return output


def openapi_document(base_url: str, release_id: str) -> dict[str, Any]:
    """Return the portable OpenAPI 3.1 contract for compatible API clients."""
    error_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message"],
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
            }
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "PMGS Reference API",
            "version": "1.0.0",
            "description": "Exact lookup of JPO-provided PMGS records without AI inference.",
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/api/v1/lookup": {
                "get": {
                    "operationId": "lookupPatentClassification",
                    "summary": "Look up one exact patent classification",
                    "parameters": [
                        {
                            "name": "scheme",
                            "in": "query",
                            "required": True,
                            "schema": {"enum": ["fi", "fterm", "ipc"]},
                        },
                        {
                            "name": "code",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "maxLength": 128},
                        },
                        {
                            "name": "release",
                            "in": "query",
                            "schema": {"type": "string", "default": "current"},
                        },
                        {"name": "edition", "in": "query", "schema": {"type": "string"}},
                        {
                            "name": "language",
                            "in": "query",
                            "schema": {"enum": ["ja", "en"], "default": "ja"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "JPO-provided classification record",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ClassificationRecord"}
                                }
                            },
                        },
                        "400": {
                            "description": "Invalid query",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                        "404": {
                            "description": "Release or classification not found",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                        "503": {
                            "description": "Release artifacts unavailable",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                    },
                }
            },
            "/api/v1/documents/{document_id}": {
                "get": {
                    "operationId": "getPmgsDocument",
                    "summary": "Get JPO-provided PMGS document text",
                    "parameters": [
                        {
                            "name": "document_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "pattern": "^doc-[a-f0-9]{24}$"},
                        },
                        {
                            "name": "release",
                            "in": "query",
                            "schema": {"type": "string", "default": "current"},
                        },
                        {
                            "name": "page",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1},
                        },
                        {
                            "name": "section",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "JPO-provided document chunk",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "400": {
                            "description": "Invalid document selector",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                        "404": {
                            "description": "Document not found",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                        "503": {
                            "description": "Release artifacts unavailable",
                            "content": {"application/json": {"schema": error_schema}},
                        },
                    },
                }
            },
            "/api/v1/releases": {
                "get": {
                    "operationId": "listPmgsReleases",
                    "responses": {"200": {"description": "Published releases"}},
                }
            },
            "/api/v1/coverage": {
                "get": {
                    "operationId": "getPmgsCoverage",
                    "responses": {"200": {"description": "Aggregate public coverage"}},
                }
            },
        },
        "components": {
            "schemas": {
                "ClassificationRecord": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "schema_version",
                        "release_id",
                        "scheme",
                        "edition",
                        "code",
                        "normalized_code",
                        "match_status",
                        "labels",
                        "texts",
                        "properties",
                        "relations",
                        "documents",
                        "sources",
                        "canonical_url",
                    ],
                    "properties": {
                        "schema_version": {"const": "1.0"},
                        "release_id": {"type": "string", "example": release_id},
                        "scheme": {"enum": ["fi", "fterm", "ipc"]},
                        "edition": {"type": ["string", "null"]},
                        "code": {"type": "string"},
                        "normalized_code": {"type": "string"},
                        "match_status": {"enum": ["exact", "normalized_exact"]},
                        "labels": {"type": "array", "items": {"type": "object"}},
                        "texts": {"type": "array", "items": {"type": "object"}},
                        "properties": {"type": "array", "items": {"type": "object"}},
                        "relations": {"type": "array", "items": {"type": "object"}},
                        "documents": {"type": "array", "items": {"type": "object"}},
                        "sources": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/PublicSource"},
                        },
                        "canonical_url": {"type": "string", "format": "uri"},
                    },
                },
                "PublicSource": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source_id",
                        "title",
                        "relative_id",
                        "owner",
                        "original_url",
                        "sha256",
                        "attribution",
                    ],
                    "properties": {
                        "source_id": {"type": "string"},
                        "title": {"type": "string"},
                        "relative_id": {"type": "string"},
                        "owner": {"type": "string"},
                        "original_url": {"type": "string", "format": "uri"},
                        "sha256": {"type": "string", "pattern": "^[A-F0-9]{64}$"},
                        "attribution": {"type": "string"},
                    },
                },
            }
        },
    }
