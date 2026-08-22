from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _section(relative: str, heading: str, next_heading: str) -> tuple[str, str]:
    text = (ROOT / relative).read_text(encoding="utf-8")
    section_start = text.index(heading)
    section_end = text.index(next_heading, section_start)
    return text, text[section_start:section_end]


def test_readmes_offer_safe_paths_for_users_without_pmgs() -> None:
    official_service = "https://www.jpo.go.jp/system/laws/sesaku/data/download.html"
    official_terms = (
        "https://www.jpo.go.jp/system/laws/sesaku/data/document/download/"
        "terms_of_use_bulk_data_download_service.pdf"
    )
    install = "uv tool install pmgs-reference"
    windows_path = chr(92).join(("C:", "path", "to", "JPPM2026002"))
    preflight = (
        f"pmgs setup {windows_path} "
        "--client none --no-register --dry-run --json"
    )

    for relative, heading, next_heading in (
        (
            "README.md",
            "## PMGSをまだ持っていない場合",
            "## PMGSを持っている人が今すぐ使う",
        ),
        (
            "README.en.md",
            "## If you do not have a PMGS package yet",
            "## Start now with a local PMGS package",
        ),
    ):
        text, section = _section(relative, heading, next_heading)

        assert official_service in section
        assert official_terms in section
        assert "docs/registered-use-terms.md" in section
        assert preflight in section
        assert "JPPM" in section
        assert text.index(install) < text.index(preflight)

    assert (ROOT / "docs/registered-use-terms.md").is_file()


def test_readmes_put_credentials_and_source_material_outside_the_support_boundary() -> None:
    _, japanese = _section(
        "README.md",
        "## PMGSをまだ持っていない場合",
        "## PMGSを持っている人が今すぐ使う",
    )
    _, english = _section(
        "README.en.md",
        "## If you do not have a PMGS package yet",
        "## Start now with a local PMGS package",
    )

    assert all(term in japanese for term in ("登録ID", "パスワード", "元のZIP", "外部AIサービス"))
    assert all(
        term in english
        for term in ("registration IDs", "passwords", "source ZIP", "external AI services")
    )
    assert "自動ダウンロードを代行しません" in japanese
    assert "does not perform JPO registration" in english
