from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def test_installation_precedes_preflight_for_new_users() -> None:
    cases = (
        ("README.md", "## PMGSをまだ持っていない場合"),
        ("README.en.md", "## If you do not have a PMGS package yet"),
    )

    for relative, heading in cases:
        section = _section((ROOT / relative).read_text(encoding="utf-8"), heading)
        install_position = section.find("uv tool install")
        preflight_position = section.find("pmgs setup")

        assert install_position >= 0, f"{relative} must install pmgs-reference in the acquisition path"
        assert preflight_position >= 0, f"{relative} must include the write-free preflight"
        assert install_position < preflight_position, (
            f"{relative} must install pmgs-reference before invoking pmgs setup"
        )
