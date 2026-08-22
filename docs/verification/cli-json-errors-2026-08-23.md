# CLI JSON error contract — 2026-08-23

Issue #19 / PR #60

## Contract

- JSON-mode exceptional failures emit exactly one JSON object on stdout.
- Exit status remains nonzero and stderr remains empty.
- The common envelope contains `schema_version`, `status`, `command`, `error.code`, and `error.message`.
- Validation-negative results retain the complete structured validation result under `details`.
- Local paths, credential-like rejected values, raw exception messages, and stack traces are not reflected.
- Human mode preserves the existing readable stderr behavior.
- UI-language localization remains outside this PR and is tracked by Issue #33.

## Covered failures

- argparse and missing-required-option errors, including always-JSON commands
- missing files and permission failures
- invalid managed `current.json`
- unsupported databases
- stable `PMGSQueryError` codes with sanitized messages
- database build failures
- `validate` results with `valid=false`
- public export I/O failures
- doctor current-pointer races
- unexpected runtime errors in JSON mode

## TDD evidence

CI run #441 verified the initial RED state: seven focused failures reproduced human argparse output, local-path leakage, incomplete envelopes, and an uncaught doctor `RuntimeError`. The suite was then expanded with unsupported-database, build, validation-negative, public-export, and unexpected-runtime cases before implementation.

The first exact-text patch failed with `parser class anchor mismatch`. A marker-based patch limited the production change to the parser class, parser construction, validation output, and `main()` exception boundary. Nested source generation initially converted nine `\n` escapes into literal line breaks; a bounded nine-replacement repair restored valid syntax. Focused tests, the full suite, mypy, Ruff, and package build then passed.

## Hosted CI evidence

Final user head: `b0d6ccf3261e71022f416b0e1b0507cd71712cdc`  
Merge ref with current `main`: `2cdd5de98f12bdd3a84b3000d383ed5180091bcd`  
GitHub Actions: CI run #479 (`32589973232`)

### Ubuntu Python 3.12

- repository boundary: success
- Ruff check: success
- Ruff format check: `114 files already formatted`
- mypy: `Success: no issues found in 30 source files`
- pytest: `300 passed, 5 skipped in 34.06s`
- wheel and sdist build: success

The five skips are pre-existing Windows-specific contracts. This change introduced no failure or skip on Ubuntu.

### Full matrix

All jobs passed:

- Python 3.12 and 3.14 on Ubuntu, Windows, and macOS
- Python 3.13 on Ubuntu
- installed wheel on Ubuntu, Windows, and macOS
- installed wheel on Python 3.13
- Cloudflare Worker on Node 22
- synthetic determinism on Ubuntu, Windows, and macOS
- cross-OS determinism comparison

## Remaining scope

This PR does not translate CLI help or human-readable output. That work remains in Issue #33. Full stderr capture is intentionally not used; JSON-mode functions are required not to emit progress before returning or raising, and the regression suite asserts an empty stderr for the covered failure paths.
