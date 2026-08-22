from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readmes_offer_safe_paths_for_users_without_pmgs() -> None:
    official_service = "https://www.jpo.go.jp/system/laws/sesaku/data/download.html"
    official_terms = (
        "https://www.jpo.go.jp/system/laws/sesaku/data/document/download/"
        "terms_of_use_bulk_data_download_service.pdf"
    )
    install = "uv tool install pmgs-reference"
    preflight = (
        r"pmgs setup C:\path\to\JPPM2026002 "
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
        text = (ROOT / relative).read_text(encoding="utf-8")
        section_start = text.index(heading)
        section_end = text.index(next_heading, section_start)
        section = text[section_start:section_end]

        assert official_service in section
        assert official_terms in section
        assert "docs/registered-use-terms.md" in section
        assert preflight in section
        assert "JPPM" in section
        assert text.index(install) < text.index(preflight)


def test_readmes_put_credentials_and_source_material_outside_the_support_boundary() -> None:
    japanese = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")

    assert all(term in japanese for term in ("登録ID", "パスワード", "元のZIP", "外部AIサービス"))
    assert all(
        term in english
        for term in ("registration IDs", "passwords", "source ZIP", "external AI services")
    )
    assert "自動ダウンロードを代行しません" in japanese
    assert "does not perform JPO registration" in english
