# CLI JSON error contract — 2026-08-23

Issue #19 / PR #60

RED: CI run #441 reproduced seven failures covering argparse errors, always-JSON commands, missing files, invalid current pointers, PMGS query errors, and doctor runtime races. The implementation must return one sanitized JSON object on stdout with a nonzero exit status and no local paths, credentials, or stack traces.

Final implementation, hosted CI evidence, review findings, and remaining limitations will be recorded after GREEN verification.
