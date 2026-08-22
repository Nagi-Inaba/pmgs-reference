# FTS5 integrity validation check

- Checked: 2026-08-22
- Scope: `concept_text_fts` and `document_text_fts`
- Result: the existing full database validation already rejects inverted-index corruption

`validate_database()` runs SQLite `PRAGMA integrity_check` before the row-level FTS parity checks. A synthetic copy of the canonical database was modified only in each FTS5 shadow data table while leaving the visible content rows intact. SQLite returned `malformed inverted index for FTS5 table ...`, and PMGS Reference returned `valid=false`.

The row-level parity checks remain useful because they separately detect missing, extra, or mismatched visible FTS rows. The regression test in `tests/test_fts_integrity_contract.py` fixes both guarantees:

1. validation does not change the database hash for a valid database;
2. corruption in either inverted index fails the existing SQLite integrity gate even when the row-level parity checks still pass.

A second writable FTS5 `integrity-check` command is therefore not added. It would duplicate a demonstrated existing gate and conflict with the validator's read-only design without increasing the observed coverage for this failure mode.
