# Local setup for Codex and Claude Code

[日本語](local-agent-kit.md)

## Scope

The local setup builds SQLite from a PMGS package that the user acquired legitimately and connects it to Codex or Claude Code through a read-only stdio MCP server.

The agent receives only three tools: `lookup_classification`, `search_pmgs`, and `get_pmgs_document`. The shared skill answers in Japanese by default, switches to `language: en` when English is requested, separates official wording from derived analysis, and never guesses a classification.

## Automated Windows setup

Run this from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both
```

The script prepares the pinned virtual environment, verifies the stable Python interpreter, inventories the source, builds a new SQLite database, validates it, performs a real stdio MCP diagnostic, generates client-specific configuration, and installs the shared skill.

It never overwrites an existing database, agent kit, or different skill with the same name. It does not change Codex or Claude Code MCP configuration unless `-RegisterClients` is supplied.

Generated files:

```text
build/local-agent-kit/
├── agent-kit.json
├── codex/config.toml
├── claude/.mcp.json
└── skill/pmgs-reference/
```

`agent-kit.json` contains resolved local paths and must not be committed.

## Register MCP

Add `-RegisterClients` to the setup command, or review the commands in `agent-kit.json` and run them manually:

```powershell
codex mcp add pmgs-reference -- C:\absolute\path\.venv\Scripts\python.exe -m pmgs_reference.cli mcp --db C:\absolute\path\current.sqlite

claude mcp add --transport stdio --scope user pmgs-reference -- C:\absolute\path\.venv\Scripts\python.exe -m pmgs_reference.cli mcp --db C:\absolute\path\current.sqlite
```

Codex uses `~/.codex/config.toml` for user configuration or `.codex/config.toml` in a trusted project. Claude Code uses `.mcp.json` for project scope and `~/.claude.json` for user scope. User scope is recommended for personal PMGS paths so absolute paths do not enter a shared repository.

See the current [Codex MCP documentation](https://developers.openai.com/codex/mcp) and [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## Install the shared skill

```powershell
uv run --frozen pmgs install-agent-skill --client both
```

| Client | Personal skill directory |
| --- | --- |
| Codex | `~/.agents/skills/pmgs-reference/` |
| Claude Code | `~/.claude/skills/pmgs-reference/` |

See the current [OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills) and [Claude Code skill documentation](https://code.claude.com/docs/en/skills).

## Generate a kit manually

```powershell
uv sync --frozen --all-groups
uv run --frozen pmgs validate C:\path\to\current.sqlite
uv run --frozen pmgs doctor --db C:\path\to\current.sqlite --json
uv run --frozen pmgs agent-kit `
  --db C:\path\to\current.sqlite `
  --output build\local-agent-kit `
  --python-executable C:\absolute\path\.venv\Scripts\python.exe `
  --client both
uv run --frozen pmgs install-agent-skill --client both
```

On Linux and macOS, pass the absolute path to that repository's `.venv/bin/python`.

## Verify

```powershell
uv run --frozen pmgs doctor --db C:\path\to\current.sqlite --json
codex mcp list
claude mcp list
```

`doctor` checks the schema and release, server identity, exact three-tool contract, read-only annotations, a real stdio lookup, and the SQLite hash before and after the lookup.

Example prompt:

```text
Use $pmgs-reference and answer in English. Look up FI G06F3/048 and cite the PMGS release and source.
```

## Update and remove

Build a new database file instead of overwriting the current one. Validate and diagnose it before changing the MCP `--db` path.

The skill installer is idempotent for identical content and refuses to overwrite a different skill. Compare the old and new copies, remove the old directory explicitly, and reinstall.

```powershell
codex mcp remove pmgs-reference
claude mcp remove pmgs-reference
```

After removal, delete local skill directories and databases only after resolving and checking their exact paths. Never post PMGS source files, SQLite, or `agent-kit.json` in issues, pull requests, or public logs.
