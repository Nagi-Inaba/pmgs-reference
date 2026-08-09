# Security Policy

## Supported versions

Security fixes are applied to the current `main` branch and the latest published release, when releases exist.

Pre-release builds and historical PMGS data releases do not receive separate security support.

## Reporting a vulnerability

Use GitHub private vulnerability reporting from the repository Security tab.

Do not open a public issue for a suspected vulnerability.

Include the affected commit or version, the exposed surface, reproduction steps using synthetic or redacted data, impact, and any known mitigation.

Do not send PMGS source packages, generated databases, credentials, registration material, private identifiers, or confidential patent documents.

Maintainers will acknowledge a complete report when it has been reviewed, but this policy does not promise a fixed response or remediation deadline.

## Security scope

Security reports may cover the Python ingestion and export boundary, SQLite read-only query layer, stdio MCP server, generated HTML and Markdown, JSON API, Cloudflare Worker routing, R2 object-key validation, dependency supply chain, or GitHub Actions configuration.

Classification-definition disagreements without a security impact belong in the classification data issue form.

PMGS Reference does not provide legal advice, patentability opinions, or model-generated classification decisions.
