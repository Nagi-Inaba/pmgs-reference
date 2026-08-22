# CLI JSON implementation verification

- newline repair: 0
- sync: 0
- format: 0
- ruff: 1
- mypy: 0
- focused pytest: 0
- full pytest: 0
- build: 0

## repair output

```
repaired=9
```

## ruff output

```
I001 [*] Import block is un-sorted or un-formatted
  --> src/pmgs_reference/cli.py:3:1
   |
 1 |   """Command-line entry point for PMGS Reference."""
 2 |
 3 | / from __future__ import annotations
 4 | |
 5 | | import argparse
 6 | | import json
 7 | | import sys
 8 | | from collections.abc import Sequence
 9 | | from pathlib import Path
10 | | from typing import Never, cast
11 | |
12 | | from pmgs_reference import __version__
13 | | from pmgs_reference.agent_kit import (
14 | |     AgentClient,
15 | |     install_agent_skills,
16 | |     prepare_agent_kit,
17 | |     resolve_clients,
18 | | )
19 | | from pmgs_reference.client_integration import ClientSelection, detect_client_targets
20 | | from pmgs_reference.data_paths import CurrentPointerError, default_data_root
21 | | from pmgs_reference.diagnostics import DEFAULT_DOCTOR_TIMEOUT_SECONDS, doctor_database
22 | | from pmgs_reference.errors import PMGSQueryError
23 | | from pmgs_reference.ingest.build import BuildError, build_database
24 | | from pmgs_reference.ingest.inventory import build_inventory, write_inventory
25 | | from pmgs_reference.mcp_server import run_stdio
26 | | from pmgs_reference.publication import (
27 | |     DEFAULT_MAX_JSON_CHUNK_BYTES,
28 | |     audit_public_release,
29 | |     export_public,
30 | |     validate_public_export,
31 | | )
32 | | from pmgs_reference.publication.validation import write_public_validation_report
33 | | from pmgs_reference.setup import (
34 | |     SetupOperationError,
35 | |     SetupResult,
36 | |     SetupUsageError,
37 | |     setup_reference,
38 | | )
39 | | from pmgs_reference.store import JSONDict, JSONValue, PMGSStore
40 | | from pmgs_reference.validation import validate_database, write_validation_report
   | |________________________________________________________________________________^
help: Organize imports
   |
41 |
   -
42 | _COMMANDS = frozenset(
   |

F841 [*] Local variable `exc` is assigned to but never used
   --> src/pmgs_reference/cli.py:777:28
    |
775 |             return _emit_failure(command, "BUILD_FAILED", "database build failed")
776 |         parser.exit(1, f"error: {exc}\n")
777 |     except RuntimeError as exc:
    |                            ^^^
778 |         if json_mode:
779 |             if command == "doctor":
    |
help: Remove assignment to unused variable `exc`
    |
776 |         parser.exit(1, f"error: {exc}\n")
    -     except RuntimeError as exc:
777 +     except RuntimeError:
778 |         if json_mode:
    |

Found 2 errors.
[*] 2 fixable with the `--fix` option.
```

## mypy output

```
Success: no issues found in 30 source files
```

## focused pytest output

```
.....................                                                    [100%]
21 passed in 3.06s
```

## full pytest output

```
........................................................................ [ 24%]
.....s..................ss....................s......................... [ 48%]
.................................................s...................... [ 72%]
........................................................................ [ 96%]
...........                                                              [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/test_build.py:1020: Windows no-replace rename contract
SKIPPED [1] tests/test_client_integration.py:66: Windows command lookup behavior
SKIPPED [1] tests/test_client_integration.py:85: Windows command lookup behavior
SKIPPED [1] tests/test_client_integration.py:322: Windows cmd.exe integration test
SKIPPED [1] tests/test_public_export.py:204: Windows junction coverage
294 passed, 5 skipped in 39.47s
```
