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

A fresh full hosted CI matrix on the corrected five-file diff is required before merge.
