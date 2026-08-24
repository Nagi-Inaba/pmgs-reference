from pathlib import Path

root = Path.cwd()


def read(rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (root / rel).write_text(text, encoding="utf-8", newline="\n")


# README JA
text = read("README.md")
start = text.index("## v0.5.0の公開状況")
end = text.index("\n## PMGSをまだ持っていない場合", start)
block = """## 現行版とv0.5.0公開準備

- [PyPI v0.4.0](https://pypi.org/project/pmgs-reference/0.4.0/)：現在の公開版です。
- [GitHub Release v0.4.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.4.0)：現在の固定Releaseです。
- [v0.5.0リリースノート](docs/releases/v0.5.0.md)：公開候補の変更点と移行方法です。
- [ソースコード](https://github.com/Nagi-Inaba/pmgs-reference)：Apache License 2.0で公開しています。

v0.5.0はrelease candidateです。検索と階層の欠落防止・ページング、文書selectorと長文取得、doctorの実MCP診断、構造化JSONエラー、FTS5完全性検査、client実行ファイル検出、3 OSのrelease gateを強化しています。`v0.5.0`タグのrelease workflowがPyPIとGitHub Releaseの公開を完了するまでは、通常のインストール先はv0.4.0です。

v0.4.0で文字列の`section`を使っていたPython呼出しは`locator`へ移行してください。また、`parents()`と`children()`は軽量なsummary recordを返すため、本文・properties・relations・documents・sourcesが必要な場合は返された識別子で`lookup()`を追加実行します。詳細は[v0.5.0リリースノート](docs/releases/v0.5.0.md)に記載しています。

配布物に含まれるのは、SQLiteを構築・検索するPythonコード、CLI、読み取り専用MCP、AI向けスキルです。PMGS原本、生成したSQLite、全量export、認証情報は配布物に含めず、GitHubやPyPIにもアップロードしていません。Claude Code用の設定と登録は自動試験済みですが、live MCP評価は`not_observed`です。実PMGSのA/B構築・Codex実MCP評価等の基礎証拠は[v0.4.0の正確性検証](docs/verification/v0.4-correctness-2026-08-12.md)を参照してください。
"""
text = text[:start] + block + text[end:]
text = text.replace(
    "v0.5.0の第一選択はPyPI版です。",
    "現在公開中のv0.4.0ではPyPI版を第一選択にします。",
)
text = text.replace(
    "検証済みのv0.5.0へ固定",
    "現在公開中のv0.4.0へ固定",
)
text = text.replace("pmgs-reference==0.5.0", "pmgs-reference==0.4.0")
text = text.replace(
    "archive/refs/tags/v0.5.0.zip",
    "archive/refs/tags/v0.4.0.zip",
)
write("README.md", text)

# README EN
text = read("README.en.md")
start = text.index("## v0.5.0 release status")
end = text.index("\n## If you do not have a PMGS package yet", start)
block = """## Current release and v0.5.0 release candidate

- [PyPI v0.4.0](https://pypi.org/project/pmgs-reference/0.4.0/): the currently published package.
- [GitHub Release v0.4.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.4.0): the current fixed release.
- [v0.5.0 release notes](docs/releases/v0.5.0.md): candidate changes and migration guidance.
- [Source code](https://github.com/Nagi-Inaba/pmgs-reference): published under the Apache License 2.0.

v0.5.0 is a release candidate. It strengthens lossless search and hierarchy pagination, document selectors and long-document retrieval, live MCP doctor checks, structured JSON errors, FTS5 integrity validation, client executable discovery, and three-OS release gates. Until the `v0.5.0` tag workflow completes both PyPI and GitHub Release publication, normal installation still resolves to v0.4.0.

Python callers that previously supplied a string `section` must migrate that value to `locator`. In addition, `parents()` and `children()` now return lightweight summary records; call `lookup()` with the returned identifiers when texts, properties, relations, documents, or sources are needed. See the [v0.5.0 release notes](docs/releases/v0.5.0.md).

The distributions contain the Python builder and query code, CLI, read-only MCP server, and AI skill. PMGS source data, generated SQLite databases, bulk exports, and credentials are neither included in the distributions nor uploaded to GitHub or PyPI. Claude Code configuration and registration pass automated tests, but live MCP behavior remains `not_observed`. The real-PMGS A/B build and live Codex evidence remain documented in the [v0.4.0 correctness verification](docs/verification/v0.4-correctness-2026-08-12.md).
"""
text = text[:start] + block + text[end:]
text = text.replace(
    "For v0.5.0, the PyPI package is the primary installation route.",
    "For the currently published v0.4.0 release, PyPI is the primary installation route.",
)
text = text.replace(
    "To pin the verified v0.5.0 release",
    "To pin the currently published v0.4.0 release",
)
text = text.replace("pmgs-reference==0.5.0", "pmgs-reference==0.4.0")
text = text.replace(
    "archive/refs/tags/v0.5.0.zip",
    "archive/refs/tags/v0.4.0.zip",
)
write("README.en.md", text)

# Current published onboarding remains v0.4.0 until tag publication.
for rel in ("docs/local-agent-kit.md", "docs/local-agent-kit.en.md"):
    text = read(rel)
    text = text.replace("v0.5.0", "v0.4.0").replace("0.5.0", "0.4.0")
    write(rel, text)

# Current status: candidate source, published distribution remains 0.4.0.
text = read("docs/current-status.md")
text = text.replace(
    "- 実装状態: v0.5.0の検索・階層・文書ページング、doctor、JSON error、FTS5検査、client探索、3 OS release gateをmainへ統合済み",
    "- 実装状態: v0.5.0の検索・階層・文書ページング、doctor、JSON error、FTS5検査、client探索、3 OS release gateをrelease candidateとして準備済み",
)
text = text.replace(
    "- 検証状態: **v0.5.0 release candidate**。hosted PR CIとtag release gateで再検証し、Claude Codeのlive MCP評価だけは`not_observed`を維持する",
    "- 検証状態: **v0.5.0 release candidate**。hosted PR CIで検証し、merge後の`v0.5.0` tag release gateで再検証する。Claude Codeのlive MCP評価だけは`not_observed`を維持する",
)
text = text.replace(
    "- 公開状態: v0.5.0をPyPIとGitHub Releaseへ同一artifactで公開する。R2、Worker、独自domain、外部検索indexは未公開のままHold",
    "- 公開状態: PyPIとGitHub Releaseの現行版はv0.4.0。v0.5.0はtag release workflowの成功後に同一artifactで公開する。R2、Worker、独自domain、外部検索indexは未公開のままHold",
)
text = text.replace(
    "Python packageの最新版はPyPIとGitHub Releaseで公開するv0.5.0である。",
    "Python packageの公開最新版はPyPIとGitHub Releaseのv0.4.0であり、v0.5.0はrelease candidateである。",
)
write("docs/current-status.md", text)

text = read("PLAN.md")
text = text.replace(
    "GitHub source repository、PyPI v0.5.0、GitHub Release v0.5.0を現在の配布面とする。",
    "GitHub source repository、PyPI v0.4.0、GitHub Release v0.4.0を現在の配布面とし、v0.5.0はrelease candidateとしてtag公開を待つ。",
)
write("PLAN.md", text)

text = read("docs/requirements-traceability.md")
text = text.replace(
    "GitHub source repository、[PyPIのv0.5.0](https://pypi.org/project/pmgs-reference/0.5.0/)、[GitHub Release v0.5.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.5.0)を現在の配布面とする。",
    "GitHub source repository、[PyPIのv0.4.0](https://pypi.org/project/pmgs-reference/0.4.0/)、[GitHub Release v0.4.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.4.0)を現在の配布面とし、v0.5.0はrelease candidateとしてtag公開を待つ。",
)
write("docs/requirements-traceability.md", text)

# Release notes remain candidate-only until publication.
text = read("docs/releases/v0.5.0.md")
text = text.replace(
    "公開日: 2026-08-24",
    "公開状態: release candidate（タグ公開前）",
)
text = text.replace(
    "## インストールと更新",
    "## 公開後のインストールと更新",
)
write("docs/releases/v0.5.0.md", text)

# Stable onboarding contract stays on published 0.4.0; package/tag guard remains 0.5.0.
text = read("tests/test_project_contracts.py")
text = text.replace(
    'archive/refs/tags/v0.5.0.zip"',
    'archive/refs/tags/v0.4.0.zip"',
)
text = text.replace(
    'pinned_install = \'uv tool install "pmgs-reference==0.5.0"\'',
    'pinned_install = \'uv tool install "pmgs-reference==0.4.0"\'',
)
text = text.replace(
    '"verified_pin": "uv tool install pmgs-reference==0.5.0"',
    '"verified_pin": "uv tool install pmgs-reference==0.4.0"',
)
anchor = "\ndef test_package_version_has_one_public_value() -> None:\n"
addition = '''

def test_release_candidate_keeps_external_links_on_the_published_v040() -> None:
    surfaces = (
        "README.md",
        "README.en.md",
        "docs/current-status.md",
        "PLAN.md",
        "docs/requirements-traceability.md",
    )
    for relative in surfaces:
        content = (ROOT / relative).read_text(encoding="utf-8")
        assert "https://pypi.org/project/pmgs-reference/0.5.0/" not in content
        assert "releases/tag/v0.5.0" not in content

    japanese = (ROOT / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "## 現行版とv0.5.0公開準備" in japanese
    assert "[PyPI v0.4.0]" in japanese
    assert "## Current release and v0.5.0 release candidate" in english
    assert "[PyPI v0.4.0]" in english


def test_v050_release_notes_cover_both_breaking_migrations() -> None:
    notes = (ROOT / "docs/releases/v0.5.0.md").read_text(encoding="utf-8")
    assert all(token in notes for token in ("`section`", "`locator`"))
    assert all(
        token in notes
        for token in ("`parents()`", "`children()`", "summary", "`lookup()`")
    )

'''
if "def test_release_candidate_keeps_external_links_on_the_published_v040" not in text:
    if anchor not in text:
        raise SystemExit("test insertion anchor missing")
    text = text.replace(anchor, addition + anchor, 1)
write("tests/test_project_contracts.py", text)
