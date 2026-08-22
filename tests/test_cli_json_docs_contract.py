from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_json_error_contract_is_documented_in_japanese_and_english() -> None:
    japanese = (ROOT / "docs" / "cli-json-errors.md").read_text(encoding="utf-8")
    english = (ROOT / "docs" / "cli-json-errors.en.md").read_text(encoding="utf-8")

    for document in (japanese, english):
        for field in (
            "schema_version",
            "status",
            "command",
            "error.code",
            "error.message",
        ):
            assert field in document
        for command in (
            "inventory",
            "build",
            "validate",
            "agent-kit",
            "install-agent-skill",
            "export-public",
            "validate-public",
            "audit-public",
        ):
            assert f"`{command}`" in document
        for boundary in (
            "ARGUMENT_ERROR",
            "FILE_NOT_FOUND",
            "CURRENT_POINTER_ERROR",
            "DATABASE_ERROR",
            "BUILD_FAILED",
            "IO_ERROR",
        ):
            assert boundary in document
        assert "--json" in document
        assert "not_found" in document
        assert "valid: false" in document

    assert "標準出力へJSON objectを1件だけ" in japanese
    assert "標準エラー出力は空" in japanese
    assert "ローカル絶対path" in japanese
    assert "exactly one JSON object" in english
    assert "Standard error is empty" in english
    assert "local absolute paths" in english
