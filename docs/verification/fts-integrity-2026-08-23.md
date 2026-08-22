# FTS5 inverted-index validation — 2026-08-23

## Scope

- `concept_text_fts`
- `document_text_fts`
- Issue #31

## Decision

The canonical database remains opened with `mode=ro`. Validation never runs FTS5's writable special command against the source database.

SQLite 3.44.0 added virtual-table `xIntegrity` checks to `PRAGMA integrity_check`. When the runtime SQLite is 3.44 or newer and the core integrity result is `ok`, PMGS Reference relies on that native content-versus-index validation and does not repeat the same full check.

Older SQLite runtimes do not provide that guarantee. Readability of `fts5vocab` alone is insufficient because a posting can be absent while the content shadow row remains readable. For the fallback, PMGS Reference therefore uses SQLite's backup API to create a disposable full database copy in a private temporary directory, closes the read-only source connection, and runs the official FTS5 `integrity-check` special command for both virtual tables on the copy. The copy is removed after validation.

The existing structural and semantic validator was moved unchanged to `validation_core.py`. The public `validation.py` facade preserves `ValidationResult`, `logical_digest`, `validate_database`, and `write_validation_report`, then adds the two dedicated FTS5 checks. This avoids rewriting or weakening the existing validation contract.

## Stable result contract

The dedicated checks expose only `expected`, `actual`, and `match`. They do not expose the runtime SQLite version or selected internal method. Those values differ across supported operating systems and would make validation reports nondeterministic even when the database and conclusion are identical.

Both successful paths therefore return the same stable payload:

```json
{"expected": "consistent", "actual": "consistent", "match": true}
```

## Failure boundary

- Missing FTS5 tables fail closed.
- A failed temporary backup fails closed.
- Posting/content inconsistency in either FTS5 table fails its dedicated check.
- Failure details are reduced to `database_error:<ExceptionType>` or `copy_error:<ExceptionType>`.
- Local paths, page contents, search terms, and raw SQLite messages are not returned.
- The final result can only remain valid when the core validator and both FTS5 checks are valid.
- The source database SHA-256 is unchanged in healthy and corrupted regression fixtures.

## Operational cost

The pre-3.44 fallback requires temporary free space approximately equal to the SQLite database size. Its additional I/O consists of one full database backup plus the two FTS5 integrity scans. SQLite 3.44 and newer avoid this copy when core integrity is already `ok`.

Hosted CI uses synthetic fixtures and is suitable for correctness and cross-platform verification, not for estimating full JPPM wall-clock time. A benchmark using the untracked full PMGS database is still required before Issue #31's production-performance criterion can be closed.

## Regression coverage

`tests/test_fts_integrity_contract.py` verifies:

1. healthy databases receive both stable checks and retain the same SHA-256;
2. the native `xIntegrity` path does not create a fallback copy;
3. the pre-3.44 path calls the copy checker and preserves the source;
4. deleting FTS5 shadow-index data while retaining content rows is rejected by the official special command on the copy;
5. arbitrary table names are rejected before SQL interpolation;
6. visible-row parity checks remain present for healthy databases;
7. successful check payloads remain identical across supported platforms.

The merge gate is the complete hosted CI matrix on the final commit, including Python 3.12/3.14 on Ubuntu, Windows, and macOS; Python 3.13 on Ubuntu; installed-wheel checks; Worker checks; and cross-OS determinism.
