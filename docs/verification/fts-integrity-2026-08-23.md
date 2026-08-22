# FTS5 inverted-index validation — 2026-08-23

## Scope

- `concept_text_fts`
- `document_text_fts`
- Issue #31

## Decision

The canonical database remains opened with `mode=ro`. Validation does not run FTS5's writable special `integrity-check` command against the source database.

SQLite 3.44.0 added virtual-table `xIntegrity` checks to `PRAGMA integrity_check`. When the runtime SQLite is 3.44 or newer and the core integrity result is `ok`, PMGS Reference relies on that native FTS5 coverage without scanning the same index twice.

Older SQLite runtimes do not provide that guarantee. On those runtimes—and whenever the core integrity result is already abnormal—the validation facade creates an `fts5vocab` table only in SQLite's temporary schema and fully aggregates its `row` view. This forces a read of the associated inverted index while leaving the source file unchanged. Temporary vocabulary tables disappear when the read-only connection closes.

The existing structural and semantic validator was moved unchanged to `validation_core.py`. The public `validation.py` facade preserves `ValidationResult`, `logical_digest`, `validate_database`, and `write_validation_report`, then adds the two dedicated FTS5 checks. This avoids rewriting or weakening the existing validation contract.

## Stable result contract

The dedicated checks intentionally expose only `expected`, `actual`, and `match`. They do not expose the runtime SQLite version, selected internal method, or vocabulary counts. Those values differ across supported operating systems and would make the validation contract nondeterministic even when the database and the validation conclusion are identical.

Both successful paths therefore return the same stable payload. The implementation path is tested through SQLite trace callbacks rather than by adding platform-dependent fields to the public report.

## Failure boundary

- Missing FTS5 tables fail closed.
- An unreadable index returns `match=false`.
- Failure details are reduced to `database_error:<ExceptionType>`.
- Local paths, page contents, search terms, and raw SQLite messages are not returned by the dedicated check.
- The final result can only remain valid when both the core validator and both FTS5 checks are valid.

## Regression coverage

`tests/test_fts_integrity_contract.py` verifies:

1. healthy databases receive both dedicated checks and retain the same SHA-256;
2. the native `xIntegrity` path does not start a redundant `fts5vocab` scan;
3. the pre-3.44 fallback path reads both indexes explicitly;
4. deleting data from either FTS5 shadow index is rejected by the fallback without modifying the corrupted fixture further;
5. arbitrary table names are rejected before SQL interpolation;
6. visible-row parity checks remain present for healthy databases;
7. successful check payloads remain identical across supported platforms.

The merge gate is the complete hosted CI matrix on the final commit, including Python 3.12/3.14 on Ubuntu, Windows, and macOS; Python 3.13 on Ubuntu; installed-wheel checks; Worker checks; and cross-OS determinism.
