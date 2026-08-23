# Canonical FTS5 schema contract — 2026-08-23

Issue #57 / PR #61

## Contract

The canonical query database contains two FTS5 virtual tables. Validation and `PMGSStore.open()` consume the same code-defined contract for both tables.

- `concept_text_fts`: `text`, `revision_id UNINDEXED`, `language UNINDEXED`, `kind UNINDEXED`
- `document_text_fts`: `text`, `document_id UNINDEXED`, `sequence_number UNINDEXED`
- both tables use exactly the `trigram` tokenizer

Column order, `UNINDEXED` flags, tokenizer, unexpected columns, and additional options are fail-closed. Public validation checks expose only stable statuses such as `columns_mismatch`, `unindexed_mismatch`, and `tokenizer_mismatch`; they do not expose SQLite DDL or local paths.

## TDD evidence

The initial RED commit demonstrated that the previous validator accepted missing `UNINDEXED` declarations, reordered or extra columns, and a document index using `unicode61`. It also showed that `PMGSStore.open()` inspected only the concept-table tokenizer and accepted a document-table mismatch.

The implementation introduces one shared parser and contract module, adds two stable validation checks, and makes Store startup reject a mismatch in either table before serving queries. Existing read-only FTS5 posting-integrity checks remain separate and continue to run after the schema gate.

## First synced CI review

The first normal CI run on a branch synchronized with `main` was run #529 (`32613213914`). Installed-wheel checks, Worker verification, and three-platform determinism completed successfully. Python matrix jobs stopped at one Ruff import-order finding in `store.py`; no test failure had been reached. Ruff's prescribed import ordering was applied without changing behavior, and the temporary one-shot workflow removed itself.

## Full hosted matrix

GitHub Actions CI run #534 (`32613317366`) tested the corrected five-file diff against `main` at `77816fc9458a0a4121dc6e3ba18e51097b193a15`. Every job completed successfully.

### Ubuntu Python 3.12

- repository boundary: `201 tracked or untracked candidate files`, success
- Ruff check: success
- Ruff format check: `117 files already formatted`
- mypy: `Success: no issues found in 31 source files`
- pytest: `316 passed, 9 skipped in 40.47s`
- wheel and sdist build: success

The skips are existing platform-specific contracts; the new FTS5 schema tests ran successfully.

### Matrix and distribution checks

- Python 3.12 and 3.14: Ubuntu, Windows, and macOS — success
- Python 3.13 on Ubuntu — success
- installed wheel: Ubuntu, Windows, macOS, and Python 3.13 — success
- Cloudflare Worker on Node 22 — success
- synthetic determinism: Ubuntu, Windows, and macOS — success
- cross-OS determinism comparison — success

A final CI run on this evidence-only commit remains the branch-protection gate before merge.
