# PMGS Reference

[日本語](README.md)

PMGS Reference is open-source software for converting a JPO Patent Map Guidance System package obtained through the official registration process into a versioned, read-only reference.

It serves source-backed FI, F-term, and IPC wording, hierarchy, editions, related documents, and attribution from one SQLite source of truth through Python, CLI, MCP, HTML, Markdown, JSON, and OpenAPI. Japanese is the default language; English is available on request.

It does not classify patents, recommend filing classifications, or produce legal opinions. Its purpose is to keep official wording separate from AI analysis.

## Recommended interfaces

| User or client | Interface |
| --- | --- |
| Codex, Claude Code, and other local AI agents | read-only stdio MCP and shared skill |
| Python applications and notebooks | `PMGSStore` Python API |
| Shell scripts and local automation | `pmgs` CLI |
| GPTs and Gems using web retrieval | optional self-hosted HTML and Markdown |
| GPT Actions and Copilot Studio | optional JSON API and a client-compatible OpenAPI definition |
| WebMCP-capable browsers | optional read-only WebMCP tool |

The source repository is public. PMGS source packages, generated SQLite databases, and full web-export trees are not included. The maintainers do not currently operate a hosted website, R2 bucket, Worker, custom domain, or PyPI release for this project.

## Use with Codex and Claude Code

On Windows, the setup script prepares the virtual environment, inventories the PMGS package, builds and validates SQLite, performs a real stdio MCP diagnostic, generates client-specific configuration, and installs the shared skill.

```powershell
git clone https://github.com/Nagi-Inaba/pmgs-reference.git
Set-Location pmgs-reference

powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both
```

The script does not change client configuration by default. Review and merge `build/local-agent-kit/agent-kit.json` and the generated fragments. Add `-RegisterClients` only when you want the script to invoke the installed Codex or Claude Code CLI and register the server.

```powershell
.\.venv\Scripts\python.exe -m pmgs_reference.cli doctor `
  --db "$env:LOCALAPPDATA\pmgs-reference\data\current.sqlite" `
  --json
```

See the [local AI agent guide](docs/local-agent-kit.en.md) for manual setup, client-specific locations, updates, and removal.

## Switch languages

The Python API and CLI default to `ja`. Pass `--language en` to the CLI or `language="en"` to Python and MCP tools. The distributed skill answers in Japanese by default and switches to English when the user requests it. Web artifacts use `/` and `/ja/` for the Japanese home and `/en/` for the English home.

```powershell
uv run --frozen pmgs lookup fi "G06F3/048" --language en --db data\pmgs-reference.sqlite --json
```

## Build the local database manually

Python 3.12 or 3.14 and [uv](https://docs.astral.sh/uv/) are required. Node.js 22 and npm 10 are only needed for Worker verification.

```powershell
uv sync --frozen --all-groups
uv run --frozen pmgs inventory C:\path\to\JPPM2026002 --output build\source-manifest.jsonl
uv run --frozen pmgs build C:\path\to\JPPM2026002 --release JPPM2026002 --output data\pmgs-reference.sqlite
uv run --frozen pmgs validate data\pmgs-reference.sqlite
uv run --frozen pmgs doctor --db data\pmgs-reference.sqlite --json
```

The package never downloads PMGS data automatically.

## Python API

```python
from pmgs_reference import PMGSStore

store = PMGSStore.open(r"C:\path\to\pmgs-reference.sqlite")
record = store.lookup("fi", "G06F3/048", language="en")
results = store.search("interaction technology", schemes=["fi", "ipc"], language="en")
```

Invalid input, unknown releases, unknown IPC editions, and valid but missing classifications remain distinct. See the [local interface contract](docs/local-interfaces.md).

## Self-host for GPTs, Gems, and Copilot Studio

The web implementation remains available for third-party deployment. An operator can use their own PMGS package, Cloudflare account, domain, and budget to generate static artifacts, upload them to R2, and serve HTML, Markdown, JSON, and OpenAPI through the Worker.

This route has limits:

- sitemap submission does not guarantee search indexing or AI retrieval;
- GPT and Gem web retrieval does not guarantee that a particular site is consulted for every answer;
- `/openapi.json` is a candidate for GPT Actions only when the current GPT editor exposes Actions and accepts OpenAPI;
- classic Gems do not necessarily support an arbitrary OpenAPI endpoint as a custom tool;
- Copilot Studio support depends on tenant policy, authentication, and connector restrictions.

See the [web self-hosting guide](docs/self-hosting.en.md) for architecture, cost categories, deployment steps, GPT and Gem examples, and security boundaries. HTML, Markdown, JSON, and OpenAPI work without WebMCP.

## Data and licensing boundary

This repository includes code, schemas, policy, synthetic fixtures, public evidence, validation records, a shared agent skill, configuration generation, diagnostics, and evaluation cases.

It excludes PMGS source packages, registration data, generated SQLite databases, full export trees, credentials, local absolute paths, and confidential patent material.

Apache-2.0 applies to this project's source code. It does not relicense JPO, INPIT, WIPO, or PMGS data. See the [registered-use notes](docs/registered-use-terms.md) and [publication policy](config/publication-policy.yaml).

## Verification

```powershell
uv lock --check
uv run --frozen python scripts/verify_repository_boundary.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest -q
uv build
npm --prefix worker ci
npm --prefix worker run verify
```

See [current status](docs/current-status.md) for measured results and external operations not performed, and the [release runbook](docs/release-runbook.md) for public export generation and auditing.

## Contributing, security, and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. Never attach PMGS source packages, generated databases, credentials, local paths, or confidential patent material to an issue or pull request.

Report suspected vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.

The source code is licensed under the [Apache License 2.0](LICENSE).
