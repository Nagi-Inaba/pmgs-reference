# PMGS Reference

PMGS Reference turns a JPO Patent Map Guidance System package obtained through the official registration process into versioned, read-only patent-classification reference interfaces.

It is designed for two kinds of use:

- local Python, CLI, and stdio MCP access to a canonical SQLite database;
- lightweight HTML, Markdown, JSON, and OpenAPI access for people, search engines, GPTs, Gemini Gems, and Copilot Studio.

PMGS Reference returns source-backed classification records and related documents.

It does not classify patents, generate legal opinions, infer missing definitions, or use a language model to rewrite official text.

## Why this project exists

PMGS is too large to maintain as a static Knowledge upload in every AI tool.

Python-only distribution also excludes managed environments that cannot install packages, including some Copilot Studio deployments.

This project therefore builds one versioned local source of truth and derives several access surfaces from it.

| User or client | Recommended interface |
| --- | --- |
| Python applications and notebooks | `PMGSStore` Python API |
| Shell scripts and local automation | `pmgs` CLI |
| Codex, Claude Code, and other local MCP clients | read-only stdio MCP |
| GPTs and Gemini Gems using web retrieval | server-rendered HTML and Markdown |
| GPT Actions and Copilot Studio | OpenAPI 3.1 and JSON API |
| WebMCP-capable browsers | optional `lookup_patent_classification` tool |

WebMCP is an enhancement, not a dependency.

The HTML, Markdown, JSON API, and OpenAPI contract remain usable when WebMCP is unavailable.

## Project status

The v1 implementation is feature-complete, and the current public-presentation contract passes synthetic-fixture validation and a full-data A/B release audit.

Implemented components include:

- deterministic PMGS inventory and lineage;
- a versioned SQLite canonical database with FTS5 search;
- Python, CLI, and read-only stdio MCP interfaces;
- deterministic HTML, Markdown, JSON, OpenAPI, sitemap, and `llms.txt` export;
- a Cloudflare Worker that serves prebuilt R2 objects;
- optional feature-detected WebMCP registration;
- validation and reproducibility auditing for public export candidates.

On 2026-08-09, two independent current-contract exports each produced 399,025 objects and matching tree SHA-256 values. Both full validators passed with zero notice errors, and the release audit reported `ready=true` with no failures.

The repository is not yet deployed, published to PyPI, connected to a public domain, or indexed by external AI tools.

See [the measured current status](docs/current-status.md) for verified counts, hashes, unresolved external checks, and the next action.

## Data and licensing boundary

This repository contains source code, schemas, synthetic fixtures, public JPO evidence documents, and verification records.

It does not contain:

- a PMGS source package;
- a generated canonical SQLite database;
- a complete public export tree;
- registration material or credentials;
- confidential patent documents.

Local users must provide the path to a PMGS package they obtained through the official registration process.

Public builds expose record-level reference pages and responses while excluding source archives, canonical database downloads, and bulk dead copies.

Generated HTML, Markdown, and AI discovery files disclose the JPO source, attribution, independent processing, and the fact that the service is not operated by the JPO or INPIT.

The Apache-2.0 license applies to this project's source code.

JPO, INPIT, WIPO, and PMGS data are not relicensed by this repository.

See [registered-use terms](docs/registered-use-terms.md) and the [publication policy](config/publication-policy.yaml) for the implemented boundary.

## Requirements

- Python 3.12 or 3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm 10 for the Worker
- a legitimately acquired PMGS package for real-data builds

PMGS ingestion, build, and query tests use only the synthetic package under `tests/fixtures/synthetic_pmgs/`.

## Local setup

```powershell
uv sync --frozen --all-groups
uv run --frozen python scripts/verify_repository_boundary.py
```

Build and validate a local canonical database.

```powershell
uv run --frozen pmgs inventory C:\path\to\JPPM2026002 --output build\source-manifest.jsonl
uv run --frozen pmgs build C:\path\to\JPPM2026002 --release JPPM2026002 --output data\pmgs-reference.sqlite
uv run --frozen pmgs validate data\pmgs-reference.sqlite
```

The package never downloads PMGS data automatically.

## Python API

```python
from pmgs_reference import PMGSStore

store = PMGSStore.open(r"C:\path\to\pmgs-reference.sqlite")

record = store.lookup("fi", "G06F3/048", language="ja")
results = store.search("相互作用技術", schemes=["fi", "ipc"], limit=20)
parents = store.parents("fi", "G06F3/048")
documents = store.related_documents("ipc", "G06F3/048", edition="8U")
release = store.release_info()
```

The API distinguishes invalid input, unknown releases, unknown IPC editions, and valid-but-not-found classifications without guessing an answer.

See [local interfaces](docs/local-interfaces.md) for the complete Python contract.

## CLI

```powershell
uv run --frozen pmgs lookup fi "G06F3/048" --db data\pmgs-reference.sqlite --json
uv run --frozen pmgs search "相互作用技術" --scheme fi --scheme ipc --db data\pmgs-reference.sqlite --json
uv run --frozen pmgs document DOCUMENT_ID --page 1 --db data\pmgs-reference.sqlite --json
```

Search is lexical.

It uses an SQLite FTS5 trigram index for terms of at least three characters and a bounded literal-substring fallback for shorter terms.

It does not perform semantic search or AI-based classification expansion.

## stdio MCP

The local MCP server exposes three read-only tools:

- `lookup_classification`
- `search_pmgs`
- `get_pmgs_document`

```powershell
uv run --frozen pmgs mcp --db data\pmgs-reference.sqlite
```

For a persistent MCP client configuration, use the absolute path to this repository's stable `.venv\Scripts\python.exe` rather than a mutable package-runner cache.

See [the MCP configuration example](docs/local-interfaces.md#stdio-mcp).

## Public export and Worker

Generate a new public candidate into an empty output directory.

```powershell
uv run --frozen pmgs export-public --db data\pmgs-reference.sqlite --policy config\publication-policy.yaml --output build\public --base-url https://pmgs.example.jp --max-json-chunk-bytes 262144
uv run --frozen pmgs validate-public build\public --report build\reports\public-validation.json
```

`export-public` refuses to overwrite an existing output directory.

The generated tree contains record-level HTML, Markdown, JSON chunks, manifests, coverage, OpenAPI, `llms.txt`, robots, and sitemaps.

It excludes source archives and the canonical SQLite database.

Verify the Worker without deploying it.

```powershell
npm --prefix worker ci
npm --prefix worker run verify
```

See the [release runbook](docs/release-runbook.md) and [Worker operations guide](worker/README.md) before any upload or deployment.

## Repository verification

Run the complete synthetic-fixture and packaging checks before claiming local release readiness.

```powershell
uv lock --check
uv run --frozen python scripts/verify_repository_boundary.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest -q
uv build
npm --prefix worker ci
npm --prefix worker run verify
```

The repository-boundary check rejects tracked or untracked publication candidates containing source packages, generated databases, archives, credential patterns, local absolute paths, oversized files, or source-like files outside the explicit synthetic/evidence allowlist.

## Repository map

| Path | Responsibility |
| --- | --- |
| `src/pmgs_reference/` | ingestion, storage, queries, CLI, MCP, and public export |
| `worker/` | Cloudflare Worker, WebMCP adapter, and runtime tests |
| `schemas/` | JSON Schema and shared normalization vectors |
| `config/` | fail-closed publication policy |
| `tests/fixtures/synthetic_pmgs/` | synthetic PMGS-shaped test package |
| `scripts/` | evidence extraction and repository-boundary verification |
| `docs/` | architecture, decisions, contracts, evidence, and release records |

## Documentation

- [Implementation plan](PLAN.md)
- [Current status](docs/current-status.md)
- [Architecture](docs/architecture.md)
- [Data contract](docs/data-contract.md)
- [Requirements traceability](docs/requirements-traceability.md)
- [Public API](docs/public-api.md)
- [Local Python, CLI, and MCP interfaces](docs/local-interfaces.md)
- [GitHub publication checklist](docs/github-publication-checklist.md)

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Do not attach PMGS source packages, generated databases, credentials, local paths, or confidential patent data to an issue or pull request.

Report suspected vulnerabilities through the process in [SECURITY.md](SECURITY.md), not through a public issue.

## License

The source code is licensed under [Apache-2.0](LICENSE).

JPO, INPIT, WIPO, and PMGS data retain their respective terms and attribution requirements.
