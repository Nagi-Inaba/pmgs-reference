# PMGS Reference Agent Guide

## Purpose and users

This repository converts a locally acquired JPO PMGS package into one versioned SQLite source of truth and several read-only reference surfaces.

The local surfaces serve Python, CLI, and stdio MCP users.

The public surfaces serve people and AI clients that need source-backed patent-classification definitions through lightweight HTML, Markdown, JSON, and OpenAPI.

Do not turn this project into a patent-classification recommender, legal-opinion system, or general AI analysis service.

## Read before changing

Read only the documents relevant to the requested change, starting with:

1. `PLAN.md` for v1 scope, exclusions, architecture, and acceptance criteria.
2. `docs/current-status.md` for measured state, unresolved external checks, and the next action.
3. `docs/requirements-traceability.md` for requirement status and completion evidence.
4. `docs/architecture.md` for component and data boundaries.
5. The applicable ADR under `docs/decisions/` before changing an established decision.
6. `docs/release-runbook.md` and `docs/github-publication-checklist.md` for release-related work.

Update the applicable source-of-truth document with any behavior, requirement, architecture, release-state, or operational change.

Do not report a local build as deployed, published, indexed, or externally available.

## Repository ownership map

- `src/pmgs_reference/` owns inventory, parsing, normalization, SQLite schema, queries, CLI, stdio MCP, and deterministic public exports.
- `worker/` owns route resolution, content negotiation, input validation, security headers, R2 reads, and optional WebMCP registration.
- `schemas/` owns JSON contracts and cross-language normalization vectors.
- `config/publication-policy.yaml` owns the fail-closed public-data boundary.
- `tests/fixtures/synthetic_pmgs/` is the only PMGS-shaped package allowed in tests and CI.
- `docs/evidence/` contains preserved public evidence and extracted text; treat source evidence as read-only unless an evidence refresh is explicitly requested.
- `scripts/verify_repository_boundary.py` enforces the tracked and untracked candidate-file publication boundary.

Keep changes within the owning component unless a cross-component contract change is required and documented.

## Data and confidentiality boundary

- Treat every external PMGS package as read-only input.
- Never commit or paste PMGS source files, generated SQLite databases, full public export trees, registration material, credentials, confidential patent documents, or real local absolute paths.
- Never copy production PMGS text into a test. Extend the synthetic fixture with invented content.
- Public outputs may contain record-level HTML, Markdown, and JSON only when allowed by `config/publication-policy.yaml`.
- Never expose a source archive, canonical database download, bulk dead copy, internal object key, stack trace, or filesystem path through a public response.
- Preserve official text separately from derived metadata, summaries, translations, and interpretation.
- Do not add automatic source downloads, scraping, telemetry, model calls, or network writes to local query paths.

Run the repository-boundary verifier after changing tracked files.

## Implementation rules

### Python

- Python owns ingestion, normalization, the canonical schema, querying, and export generation.
- Keep builds deterministic and retain source lineage.
- Reject unknown formats and unsafe publication states instead of guessing.
- Keep the query layer read-only; verify that query operations do not mutate the canonical database.
- Preserve the distinction between FI, F-term, and IPC, including IPC editions.
- Use parameterized SQLite queries and bounded response sizes.

### Worker and public interfaces

- The Worker may validate, resolve, and serve prebuilt objects; it must not become a second source of classification truth.
- Resolve R2 keys from validated manifests and fixed prefixes, never directly from untrusted input.
- Maintain the maximum two-read lookup contract and the 8 MiB JSON fail-closed limit unless an ADR changes them.
- Keep normal HTML, Markdown, JSON, and OpenAPI usable without WebMCP.
- Register WebMCP only through feature detection and expose read-only tools.
- Do not add model inference, semantic search, D1, Vectorize, Workers AI, or Remote MCP to v1.

### Schemas and generated artifacts

- Update JSON Schema, normalization vectors, fixtures, Python behavior, Worker behavior, and documentation together when a shared contract changes.
- Do not hand-edit generated Worker bindings or bundled WebMCP output; use the documented generation commands.
- Do not overwrite an existing public export directory.
- Keep real build outputs under ignored `build/` or `data/` paths and outside Git history.

## Verification

Run focused tests while editing.

Before claiming the repository is locally release-ready, run:

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

For changes involving real data or public artifacts, also follow `docs/release-runbook.md` and record the required A/B export, validation, hashes, coverage, and audit evidence.

Validate structured files with parsers.

Check Markdown links after documentation changes.

Record measured results, failures, skipped checks, and residual risks in `docs/current-status.md` or the applicable verification record.

## Git and external actions

- Preserve unrelated user changes and a dirty worktree.
- Use focused diffs and Conventional Commit subjects for requested commits.
- Do not commit unless the active user request authorizes a commit.
- Do not create or change a remote, push, open a pull request, create a release, publish a package, upload to R2, deploy a Worker, change a domain, or change repository visibility without explicit authorization for that external action.
- Never rewrite published history or use destructive Git recovery commands unless the user explicitly requests the exact operation.
- Before an authorized GitHub commit or push, verify that the effective Git email ends in `@users.noreply.github.com`.

## Completion report

Lead with the outcome.

Report:

1. files and behavior actually changed;
2. commands and measured evidence used for verification;
3. skipped checks, failures, external state, and residual risk;
4. the smallest remaining action, when one exists.

Keep implemented, locally verified, committed, pushed, deployed, published, and live states distinct.
