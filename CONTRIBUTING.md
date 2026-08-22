# Contributing to PMGS Reference

PMGS Reference accepts changes that improve deterministic ingestion, local read-only reference tools, public record-level artifacts, or their verification.

The project does not accept PMGS source packages, generated databases, full public export trees, registration material, credentials, or confidential patent data.

## Development setup

Use Python 3.12, 3.13, or 3.14, `uv`, Node.js 22, and npm 10.

```powershell
uv sync --frozen --all-groups
Set-Location worker
npm ci
```

Tests and CI use only the synthetic package under `tests/fixtures/synthetic_pmgs/`.

Do not replace it with copied production data.

## Before opening a pull request

Run the Python release checks from the repository root.

```powershell
uv lock --check
uv run --frozen python scripts/verify_repository_boundary.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest -q
uv build
```

Run the Worker checks from `worker/`.

```powershell
npm ci
npm run verify
```

Update the applicable architecture, decision, status, runbook, or requirement evidence when behavior changes.

Keep official source text separate from derived metadata, summaries, translations, or legal interpretation.

## Pull requests

Keep each pull request focused on one outcome.

Describe its non-goals and include the exact verification commands and results.

Use Conventional Commit subjects such as `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `ci:`, or `chore:`.

Do not disclose a suspected vulnerability in a public issue.

Follow [SECURITY.md](SECURITY.md) instead.

By contributing, contributors agree that their code contributions are licensed under Apache-2.0.
