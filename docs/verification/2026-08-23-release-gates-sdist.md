# Release gates and sdist verification — 2026-08-23

Issues #20 and #34

## Contract

- The tag workflow builds exactly one wheel and one sdist once.
- Linux, Windows, and macOS download that fixed artifact set.
- Each OS runs the source suite, installed-wheel E2E, sdist-derived-wheel E2E, and synthetic determinism.
- The sdist extractor rejects absolute paths, traversal, backslashes, links, special files, duplicate paths, unexpected roots, excessive member counts, and excessive uncompressed size.
- The wheel rebuilt from the sdist must match the release wheel in runtime payload hashes and distribution metadata; `RECORD` is excluded because it is derived from the wheel contents.
- A dedicated gate rejects missing, extra, non-file, or symbolic-link distribution entries and verifies wheel/sdist project metadata.
- Worker verification and the three-platform determinism comparison are required before PyPI publication.

## Local evidence

The focused contract suite was run against the implementation:

```text
PYTHONPATH=src python -m pytest -q tests/test_release_gate_contract.py tests/test_release_scripts.py -k 'not synthetic_determinism_report_is_valid_and_path_free and not synthetic_pdf_generation_is_byte_reproducible'
21 passed, 2 deselected
```

Two pre-existing synthetic-PDF tests cannot be reproduced in this container because its system PyMuPDF is 1.26.7 and lacks the project-pinned `reproducible=True` API. The required hosted matrix uses the locked PyMuPDF 1.28 series and remains the merge authority.

## Merge gate

Before merge, the pull-request merge ref must pass the complete hosted matrix, including all required branch-protection checks. The first real tag using this workflow is also the operational proof that no publication job starts before every release gate succeeds.
