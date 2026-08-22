# FTS5 inverted-index validation — 2026-08-23

## Scope

- `concept_text_fts`
- `document_text_fts`
- Issue #31

## Decision

The canonical database is never opened for writing. The existing structural and semantic validator remains content-identical in `validation_core.py`; the public `validation.py` facade adds two dedicated FTS5 checks while preserving `ValidationResult`, `logical_digest`, `validate_database`, and `write_validation_report`.

Before either validation path is trusted, `sqlite_schema.sql` must identify both expected objects as `CREATE VIRTUAL TABLE ... USING fts5(...)`. A missing object or an ordinary table using the expected name fails closed before a native result or temporary copy can be treated as valid.

SQLite 3.44.0 added virtual-table `xIntegrity` coverage to `PRAGMA integrity_check`. SQLite 3.45.1 fixed read-only databases containing FTS3 and FTS5 tables. PMGS Reference therefore relies on native `PRAGMA integrity_check` coverage only on SQLite 3.45.1 or newer and only when the core integrity result is `ok`.

For earlier SQLite runtimes, or when the core integrity result is already abnormal, validation creates a disposable full database copy using SQLite's backup API. The source connection uses `mode=ro` and `query_only`. The copy is opened for writing, its FTS5 object identity is checked again, and each FTS5 table receives the official `integrity-check` special command. This checks both the internal index structures and, for these non-external-content tables, consistency between the stored content and the inverted index.

The disposable copy is closed and removed before validation returns. A copy, cleanup, schema, or SQLite failure fails closed. The source database SHA-256 is verified unchanged by regression tests.

## Stable result contract

Dedicated checks expose only `expected`, `actual`, and `match`. They do not expose the runtime SQLite version, selected internal method, temporary path, database path, vocabulary counts, raw SQLite messages, page contents, or search terms.

Both successful paths return the same payload:

```json
{"expected": "consistent", "actual": "consistent", "match": true}
```

This keeps validation reports and synthetic determinism identical across supported operating systems.

## Failure boundary

- Missing FTS5 tables fail closed.
- A non-FTS object using an expected FTS5 name fails with `actual=not_fts5`.
- Content-versus-index mismatch returns `match=false`.
- FTS5 failures are reduced to `database_error:<ExceptionType>`.
- Backup and temporary-storage failures are reduced to `copy_error:<ExceptionType>`.
- Temporary-copy cleanup failure cancels a successful result instead of being ignored.
- The final result is valid only when the core validator and both FTS5 checks are valid.

## Regression coverage

`tests/test_fts_integrity_contract.py` verifies:

1. healthy databases receive both dedicated checks and retain the same SHA-256;
2. SQLite 3.44.0 through 3.45.0 use the fallback because read-only native coverage is not reliable;
3. SQLite 3.45.1 and newer may use the native path;
4. the native path does not create a redundant database copy;
5. the fallback checks one disposable copy and preserves the source;
6. a content shadow row can remain visible while its postings are absent, the existing visible-row parity still succeeds, and the exact copy check rejects the database;
7. an ordinary table with the expected FTS5 name can satisfy the legacy row parity but is rejected before native trust;
8. backup failure is sanitized and fails both indexes;
9. arbitrary table names are rejected before SQL interpolation;
10. successful check payloads remain identical across supported platforms.

## Cost and unobserved evidence

The fallback requires temporary free space for a complete SQLite copy and then performs the native FTS5 integrity scan on that copy. This is deliberately a full-validation path, not a cheap health check. Hosted CI measures the synthetic fixture only. Runtime and temporary-disk usage on the full JPPM database remain to be measured separately before making a performance claim.

The merge gate is the complete hosted CI matrix on the final commit, including Python 3.12/3.14 on Ubuntu, Windows, and macOS; Python 3.13 on Ubuntu; installed-wheel checks; Worker checks; and cross-OS determinism.
