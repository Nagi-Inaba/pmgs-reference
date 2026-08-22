# CLI JSON error contract — 2026-08-23

Issue #19 / PR #60

## RED evidence

CI run #441 reproduced the expected failures for argparse errors, always-JSON commands, missing files, invalid current pointers, PMGS query errors, and doctor runtime races. The expanded RED suite additionally covers unsupported databases, build failures, validation-negative results with retained details, public export failures, and unexpected runtime errors.

## Required contract

- exceptional failures emit exactly one JSON object on stdout;
- exit status remains nonzero;
- stderr is empty in JSON mode;
- the common envelope contains `schema_version`, `status`, `command`, `error.code`, and `error.message`;
- validation-negative results retain the structured validation result under `details`;
- local paths, credentials, raw exception text, and stack traces are not reflected;
- human mode keeps the existing readable stderr behavior;
- UI-language localization remains outside this PR and is tracked by Issue #33.

The first exact-text patch failed with `parser class anchor mismatch`. The marker-based v2 patch applied the intended regions, but nested source generation converted nine `\n` escapes into literal line breaks inside f-strings. A bounded nine-replacement repair now restores those escapes before running format, mypy, focused tests, the full suite, and package build.
