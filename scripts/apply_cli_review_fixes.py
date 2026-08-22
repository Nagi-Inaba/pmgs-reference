from __future__ import annotations

from pathlib import Path


def apply() -> None:
    path = Path("src/pmgs_reference/cli.py")
    text = path.read_text(encoding="utf-8")

    import_anchor = "import json\nimport sys\n"
    if text.count(import_anchor) != 1:
        raise SystemExit("sqlite import anchor mismatch")
    text = text.replace(import_anchor, "import json\nimport sqlite3\nimport sys\n", 1)

    old_json_mode = '''def _wants_json(argv: Sequence[str], command: str | None) -> bool:
    return command in _ALWAYS_JSON_COMMANDS or "--json" in argv
'''
    new_json_mode = '''def _wants_json(argv: Sequence[str], command: str | None) -> bool:
    option_tokens = list(argv)
    if "--" in option_tokens:
        option_tokens = option_tokens[: option_tokens.index("--")]
    return command in _ALWAYS_JSON_COMMANDS or "--json" in option_tokens
'''
    if text.count(old_json_mode) != 1:
        raise SystemExit("JSON-mode anchor mismatch")
    text = text.replace(old_json_mode, new_json_mode, 1)

    exception_anchor = '''    except ValueError as exc:
        if json_mode:
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
'''
    replacement = '''    except sqlite3.DatabaseError as exc:
        if json_mode:
            if command == "build":
                return _emit_failure(command, "BUILD_FAILED", "database build failed")
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
    except ValueError as exc:
        if json_mode:
            code, message = _value_error_code(command)
            return _emit_failure(command, code, message)
        parser.exit(1, f"error: {exc}\\n")
'''
    if text.count(exception_anchor) != 1:
        raise SystemExit("SQLite exception anchor mismatch")
    text = text.replace(exception_anchor, replacement, 1)

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    apply()
