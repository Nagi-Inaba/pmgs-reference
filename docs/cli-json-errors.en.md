# CLI JSON error contract

When PMGS Reference is called from CI, shell scripts, or AI agents, machine-readable invocations keep standard output to exactly one JSON object on failure.

## When JSON mode applies

The following query-oriented commands enter JSON mode when `--json` is supplied:

- `setup`
- `lookup`
- `search`
- `document`
- `doctor`

The following commands already use JSON for successful output. Their parse errors and runtime errors therefore use the same JSON envelope even when `--json` is omitted:

- `inventory`
- `build`
- `validate`
- `agent-kit`
- `install-agent-skill`
- `export-public`
- `validate-public`
- `audit-public`

## Failure envelope

```json
{
  "schema_version": "1.0",
  "status": "failed",
  "command": "validate",
  "error": {
    "code": "FILE_NOT_FOUND",
    "message": "requested file was not found"
  }
}
```

The contract is:

- Standard output contains exactly one JSON object.
- Standard error is empty for a JSON failure.
- The process keeps a nonzero exit status. Argument errors use 2; runtime errors normally use 1.
- `schema_version`, `status`, `command`, `error.code`, and `error.message` are stable fields.
- `error.code` is selected from the exception type and failure domain. Representative values include `ARGUMENT_ERROR`, `FILE_NOT_FOUND`, `CURRENT_POINTER_ERROR`, `DATABASE_ERROR`, `BUILD_FAILED`, and `IO_ERROR`.
- `error.message` is a stable machine-oriented summary, not the raw exception message.
- JSON errors do not contain local absolute paths, credentials, stack traces, raw SQLite errors, or PMGS text.

## Successful and negative domain results

The common error envelope is used only when the operation could not be performed. Existing domain payloads are preserved for:

- `not_found`, `version_not_found`, and `not_valid_at_release` from `lookup --json`;
- `valid: false` from `validate`;
- validation mismatches from `validate-public`;
- structured diagnostic results from `doctor --json`.

These are domain results, so the CLI facade does not rewrite them into the common error envelope. Consumers should inspect both the payload and the exit status.

## Human-readable mode

Without JSON mode, the existing help, progress, and human-readable output remain in place. Failures are written as readable text to standard error and retain a nonzero exit status.

## Examples

```powershell
pmgs lookup fi "G06F3/048" --json
pmgs doctor --timeout-seconds 30 --json
pmgs validate C:\path\to\pmgs.sqlite
```

A JSON consumer can parse standard output as JSON without switching between text and JSON parsers. When additional non-sensitive diagnostic detail is required, use human-readable mode or a separately written validation report.
