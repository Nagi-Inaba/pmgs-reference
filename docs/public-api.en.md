# Public API contract

[日本語](public-api.md)

## Classification lookup

```http
GET /api/v1/lookup?scheme=fi&code=G06F3%2F048&release=current&language=en
```

`scheme` and `code` are required.

`scheme` must be one of `fi`, `fterm`, or `ipc`.

`language` must be `ja` or `en` and defaults to `ja`.

`version` is available only for IPC and must use the `YYYY.MM` form.
Supplying it for FI or F-term returns `INVALID_VERSION`.
`relation_limit` defaults to 50 and has a maximum of 200, while `relation_offset` defaults to 0.

All revisions for one code are stored in one bundle.
The Worker does not calculate validity periods; it selects either the precomputed reference-date record or the requested entry from `revision_records`.
A missing requested version and the absence of a revision valid on the reference date are normal HTTP 200 responses with `version_not_found` and `not_valid_at_release`, respectively.

## Document lookup

```http
GET /api/v1/documents/{document_id}?release=current&page=1
```

`document_id` must exist in the export manifest.

`page` and `section` are optional and cannot be supplied together.

`release` defaults to `current`.
Only public releases listed in the Worker's release catalog can be selected.

## HTTP status contract

| Condition | HTTP | code |
|---|---:|---|
| Success | 200 | none |
| Invalid scheme | 400 | `INVALID_SCHEME` |
| Invalid code | 400 | `INVALID_CODE` |
| Invalid language | 400 | `INVALID_LANGUAGE` |
| Version supplied for FI or F-term, or an invalid version form | 400 | `INVALID_VERSION` |
| IPC version not found | 200 | `match_status=version_not_found` |
| No revision valid on the reference date | 200 | `match_status=not_valid_at_release` |
| Unknown release | 404 | `RELEASE_NOT_FOUND` |
| Classification not found | 404 | `CLASSIFICATION_NOT_FOUND` |
| Document not found | 404 | `DOCUMENT_NOT_FOUND` |
| Inconsistent release artifacts | 503 | `RELEASE_UNAVAILABLE` |

The API returns `Access-Control-Allow-Origin: *`.

Every response includes `Content-Signal: search=yes, ai-input=yes, ai-train=no` and security headers.

Versioned responses use long-lived caching; `current` responses use short-lived caching.

A normal classification or document lookup completes with at most two R2 reads: one manifest and one target chunk.
The Worker returns 503 rather than guessing when artifacts are inconsistent or a JSON object exceeds 8 MiB.

## Security boundary

User input is never concatenated directly into an R2 key.

The Worker resolves R2 keys from validated manifests and fixed prefixes.

Error responses do not expose local paths, internal keys, or stack traces.

## Public artifact contract

`pmgs export-public` requires `base_url` and generates:

- `/releases/{release}/groups/.../manifest.json`: lookup key ranges and JSON chunk hashes
- `/releases/{release}/groups/.../{chunk}.json`: storage records containing official Japanese and English values
- `/releases/{release}/site/{language}/.../{chunk}.html`: pages readable without JavaScript
- `/releases/{release}/site/{language}/.../{chunk}.md`: equivalent Markdown for retrieval clients
- `/releases/{release}/documents/{document_id}/...`: official document manifests and section chunks
- `/releases/{release}/manifest.json`: bytes, SHA-256, and content type for every public object

Storage records contain Japanese and English values together.

Classification record 2.0 includes `reference_date`, `record_status`, the selected `version` and its validity period, and `available_versions`.
Relations are returned in stable pages with `relation_count`, `relation_offset`, `relation_limit`, `relations_truncated`, and `next_relation_offset`.

A bundle for one code never crosses a JSON chunk boundary.
The export fails if a single classification bundle exceeds the fixed 256 KiB limit.

At request time, the Worker projects only source-derived values in the selected language into `classification-record.schema.json`.

Every source object requires `source_id`, `title`, `relative_id`, `owner`, `original_url`, `sha256`, and `attribution`.

`original_url` points to the JPO source-information page.
The exporter does not infer per-file download URLs for the PMGS package.

The public URL omits the chunk number for chunk `001` and appends the number for `002` and later chunks.
A classification fragment always points to a page that actually contains that classification.

`index.html` and `llms.txt` are the canonical Japanese entry points.
`index.en.html` and `llms.en.txt` are the English alternatives.
The Worker serves the Japanese top page at `/` and `/ja/`, and the English top page at `/en/`.

The same build generates `openapi.json`, `robots.txt`, and `sitemap.xml`.
Public artifacts do not contain source CSV, XML, PDF files, the canonical SQLite database, or a bulk JSON dump.

## HTML and WebMCP

Classification pages remain readable as ordinary HTML without JavaScript.

`Accept: text/markdown` returns prebuilt Markdown with the same release and source attribution.

HTML, Markdown, both language top pages, and both `llms.txt` files contain attribution, the JPO source-information URL, a transformation notice, and an unofficial-service notice.

The validator rejects a candidate with missing notices through `notice_errors`.

Every HTML page loads `/assets/webmcp.js` as an optional layer.
When the browser exposes `document.modelContext`, the script registers one read-only `lookup_patent_classification` tool.
That tool calls the same-origin classification API and does not generate a separate definition or AI summary.

GPTs and Gems can use HTML, Markdown, and the sitemap as web-retrieval entry points, but indexing and use of a particular domain are not guaranteed.

`openapi.json` is the entry point for OpenAPI 3.1 clients.
If GPT Actions or Copilot Studio requires another OpenAPI version, generate a compatible definition from the same HTTP contract and test it separately.
