# Codex and Claude Code setup

## Start using PMGS Reference

You need a PMGS package acquired after registration and [uv](https://docs.astral.sh/uv/).

After v0.4.0 is available on PyPI:

```powershell
uv tool install pmgs-reference
pmgs setup C:\path\to\JPPM2026002
```

To use the current GitHub source, run `uv tool install .` in the repository and then use the same `pmgs setup` command.

Setup performs these stages:

1. Inventory the PMGS package and fix a logical SHA-256 for every source file.
2. Reuse an identical verified SQLite database or build a new candidate.
3. Re-inventory the source to detect changes during the build.
4. Validate SQLite and run a real stdio MCP diagnostic.
5. Activate only the verified database.
6. Register the MCP server and shared skill with the selected clients.

When Codex or Claude Code is detected, setup asks for confirmation. Press Enter to accept the default:

```text
Register PMGS Reference with codex? [Y/n]
```

Open a new agent session and ask:

```text
Use $pmgs-reference to look up the definition, hierarchy, edition, and sources for FI G06F3/048.
```

## Select clients

`--client auto` is the default and detects installed Codex and Claude Code clients. Use explicit options when you want a fixed target or non-interactive behavior.

```powershell
pmgs setup C:\path\to\JPPM2026002 --client codex --register
pmgs setup C:\path\to\JPPM2026002 --client claude --register
pmgs setup C:\path\to\JPPM2026002 --client both --register
pmgs setup C:\path\to\JPPM2026002 --client none --no-register
```

An identical MCP registration or skill is reused. A different existing item with the same name is left unchanged and reported as a conflict.

When Claude Code uses `CLAUDE_CONFIG_DIR`, setup inspects and updates the MCP configuration and `skills/pmgs-reference` inside that custom profile.

## Update the PMGS release

Run setup with the new package:

```powershell
pmgs setup C:\path\to\JPPM2027001
```

The new SQLite file is stored separately from older releases. Setup atomically changes only `current.json` after validation and the MCP diagnostic, so a failed update leaves the previous active release unchanged. Older databases are not deleted automatically.

The MCP registration points to the managed data directory, so it does not need to be rewritten for each release. Restart an active Codex or Claude Code session after switching releases.

## Data locations

The default managed data directory depends on the operating system.

| OS | Data directory |
| --- | --- |
| Windows | `%LOCALAPPDATA%\pmgs-reference` |
| macOS | `~/Library/Application Support/pmgs-reference` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/pmgs-reference` |

The main layout is:

```text
pmgs-reference/
├── state/current.json
├── data/releases/<release>/<source-sha256>/<database-sha256>.sqlite
├── reports/<setup-run>/
└── staging/
```

Use `--data-dir` for another location:

```powershell
pmgs setup C:\path\to\JPPM2026002 --data-dir C:\path\to\pmgs-data
pmgs doctor --data-dir C:\path\to\pmgs-data --json
```

Python accepts the same location through `PMGSStore.open(data_dir=...)`; CLI commands accept `--data-dir`.

## Automation and JSON output

Non-interactive setup must explicitly choose registration behavior:

```powershell
pmgs setup C:\path\to\JPPM2026002 `
  --client both `
  --register `
  --non-interactive `
  --json
```

Use `--client none --no-register` to prepare only the local database. Add `--dry-run` to resolve and inventory the source without changing the data directory or client configuration.

Exit code `0` means setup completed or reused an existing database, `1` means a build, diagnostic, or registration failure, and `2` means invalid usage. JSON mode writes exactly one result object to standard output and sends progress to standard error.

## Diagnose the installation

```powershell
pmgs doctor --json
codex mcp list
claude mcp list
```

`doctor` checks the SQLite schema and release, the exact three-tool contract, read-only annotations, a real stdio lookup, and the SQLite hash before and after the lookup. For a managed data directory, it also compares the file SHA-256 with `current.json` and confirms that the current pointer did not switch during the diagnostic. Routine lookups do not rehash the entire large database, so run `doctor` first after any external database edit or when corruption is suspected.

## Run from the repository

The Windows script is a thin adapter over `pmgs setup`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -Client codex `
  -RegisterClients
```

On other operating systems, run `uv run --frozen pmgs setup ...` directly.

## Remove client registrations

```powershell
codex mcp remove pmgs-reference
claude mcp remove pmgs-reference
```

Before deleting SQLite files, inspect `state/current.json` and remove only old releases that are no longer active.
