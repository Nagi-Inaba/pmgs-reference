# PMGS Reference

[English](README.en.md)

PMGS Referenceは、正規の利用登録を経て取得した特許庁のパテントマップガイダンス（PMGS）を、版付きの読み取り専用リファレンスとして利用するためのオープンソースソフトウェアです。

FI、Fターム、IPCの公式文言、階層、版、関連資料、出典を、同じSQLite正本からPython、CLI、MCP、HTML、Markdown、JSON、OpenAPIへ提供します。日本語を既定言語とし、英語にも切り替えられます。

このソフトウェアは、特許へ分類を付与せず、出願分類を推薦せず、法的見解を生成しません。公式文言とAIによる分析を分けるための参照基盤です。

## 利用方法

| 利用者・クライアント | 推奨インターフェース |
| --- | --- |
| Codex、Claude Code、その他のローカルAIエージェント | 読み取り専用stdio MCPと共通スキル |
| Pythonアプリ、Notebook | `PMGSStore` Python API |
| シェルスクリプト、ローカル自動処理 | `pmgs` CLI |
| GPTs、GemなどWeb検索を使うAI | 任意セルフホストのHTML・Markdown |
| GPT Actions、Copilot Studio | 任意セルフホストのJSON APIと環境互換のOpenAPI定義 |
| WebMCP対応ブラウザ | 任意の読み取り専用WebMCP tool |

リポジトリのソースコードはGitHubで公開しています。PMGS原資料、生成済みSQLite、全量Web成果物は同梱しません。Webサイト、R2、Worker、独自ドメイン、PyPIは、このリポジトリの管理者が運営する公開サービスとしては提供していません。

## Codex・Claude Codeで使う

Windowsでは、次のスクリプトが仮想環境の準備、PMGSの棚卸し、SQLite生成、検証、実stdio MCP診断、クライアント別設定の生成、共通スキルの導入を順に行います。

```powershell
git clone https://github.com/Nagi-Inaba/pmgs-reference.git
Set-Location pmgs-reference

powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both
```

既定ではクライアント設定を変更しません。生成された`build/local-agent-kit/agent-kit.json`と設定断片を確認してマージしてください。CodexまたはClaude CodeのCLIへMCPを登録する場合だけ、`-RegisterClients`を追加します。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both `
  -RegisterClients
```

セットアップ後の診断は、データベースのハッシュを照会前後で比較し、実際のstdio接続、公開tool、読み取り専用annotation、サンプル照会を検査します。

```powershell
.\.venv\Scripts\python.exe -m pmgs_reference.cli doctor `
  --db "$env:LOCALAPPDATA\pmgs-reference\data\current.sqlite" `
  --json
```

クライアント別の設定先、手動導入、更新、削除方法は[ローカルAIエージェント導入ガイド](docs/local-agent-kit.md)に記載しています。

## 日本語と英語の切替

Python APIとCLIの既定値は`ja`です。

```powershell
# 日本語（既定）
uv run --frozen pmgs lookup fi "G06F3/048" --db data\pmgs-reference.sqlite --json

# 英語
uv run --frozen pmgs lookup fi "G06F3/048" --language en --db data\pmgs-reference.sqlite --json
```

MCPではtool引数の`language`へ`ja`または`en`を渡します。配布スキルは日本語での回答を既定とし、利用者が英語を指定したときだけ英語へ切り替えます。Web成果物では`/`と`/ja/`が日本語top、`/en/`が英語topです。

## ローカルデータベースを手動で作る

要件はPython 3.12または3.14と[uv](https://docs.astral.sh/uv/)です。Workerを検証する場合だけNode.js 22とnpm 10も必要です。

```powershell
uv sync --frozen --all-groups
uv run --frozen pmgs inventory C:\path\to\JPPM2026002 --output build\source-manifest.jsonl
uv run --frozen pmgs build C:\path\to\JPPM2026002 --release JPPM2026002 --output data\pmgs-reference.sqlite
uv run --frozen pmgs validate data\pmgs-reference.sqlite
uv run --frozen pmgs doctor --db data\pmgs-reference.sqlite --json
```

本パッケージがPMGSデータを自動取得することはありません。

## Python API

```python
from pmgs_reference import PMGSStore

store = PMGSStore.open(r"C:\path\to\pmgs-reference.sqlite")

record = store.lookup("fi", "G06F3/048", language="ja")
results = store.search("相互作用技術", schemes=["fi", "ipc"], limit=20)
parents = store.parents("fi", "G06F3/048")
documents = store.related_documents("ipc", "G06F3/048", edition="8U")
release = store.release_info()
```

入力不正、未知のリリース、未知のIPC版、該当なしを区別し、存在しない定義を推測しません。詳細は[ローカル参照インターフェース](docs/local-interfaces.md)を参照してください。

## GPTs・Gem・Copilot Studio向けにWeb公開する

Web公開用コードは残してあります。第三者が自分のPMGS原資料、Cloudflareアカウント、ドメイン、予算を用意すれば、静的成果物をR2へ置き、Cloudflare WorkerからHTML、Markdown、JSON、OpenAPIを配信できます。

この経路には、次の制約があります。

- 検索エンジンへサイトマップを送信しても、クロールやAIからの参照は保証されません。
- GPTsのWeb検索とGemのWeb参照は、毎回答で特定サイトを必ず使う仕組みではありません。
- GPT Actionsは、利用中のGPT編集画面がActionsとOpenAPI取込みに対応している場合に限り、`/openapi.json`を接続候補にできます。
- 現行の一般的なGemへ、任意のOpenAPIを直接toolとして登録できるとは限りません。公開サイトを検索対象にし、Gemの指示で参照先ドメインを指定する方法はbest effortです。
- Copilot Studioとの接続可否は、組織の管理ポリシー、認証方式、コネクタ制限に依存します。

構成、費用項目、公開手順、GPTs・Gem向け設定例、セキュリティ境界は[Webセルフホストガイド](docs/self-hosting.md)にまとめています。通常のHTML、Markdown、JSON、OpenAPIはWebMCPがなくても動作します。

## データとライセンスの境界

このリポジトリに含まれるもの：

- ソースコード、JSON Schema、公開ポリシー
- 合成したPMGS形式のtest fixture
- 出典確認用の公開資料と検証記録
- Codex・Claude Code用の共通スキル、設定生成、診断、評価ケース

含まれないもの：

- PMGS原資料と取得用の登録情報
- 生成済みSQLiteと全量Web成果物
- 認証情報、秘密鍵、ローカル絶対パス
- 非公開の特許資料

Apache-2.0は本リポジトリのソースコードへ適用されます。特許庁、INPIT、WIPO、PMGSのデータを再ライセンスするものではありません。[登録条件と公開形態](docs/registered-use-terms.md)と[公開ポリシー](config/publication-policy.yaml)も確認してください。

## 検証

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

公開境界検査は、PMGS原資料、生成DB、archive、認証情報、実在するローカル絶対パス、過大ファイルなどがGit候補へ混入した場合に失敗します。

現在の実測値と未実施の外部操作は[現在の状態](docs/current-status.md)、公開候補の生成と監査は[リリース手順](docs/release-runbook.md)に記録しています。

## リポジトリ構成

| パス | 役割 |
| --- | --- |
| `src/pmgs_reference/` | 取込み、SQLite、検索、CLI、MCP、公開成果物生成 |
| `src/pmgs_reference/resources/skills/` | Codex・Claude Code共通スキル |
| `evals/` | AIエージェントの動作評価ケース |
| `worker/` | Cloudflare Workerと任意WebMCP |
| `schemas/` | JSON Schemaと正規化ベクトル |
| `config/` | fail closedの公開ポリシー |
| `tests/fixtures/synthetic_pmgs/` | 合成PMGS形式のtest package |
| `scripts/` | セットアップ、証跡抽出、公開境界検査 |
| `docs/` | 設計、契約、判断記録、運用手順、検証記録 |

## 開発参加とセキュリティ

変更を提案する前に[CONTRIBUTING.md](CONTRIBUTING.md)を確認してください。IssueやPull RequestへPMGS原資料、生成DB、認証情報、ローカルパス、非公開の特許資料を添付しないでください。

脆弱性の疑いは公開Issueではなく、[SECURITY.md](SECURITY.md)に記載した方法で報告してください。

## ライセンス

ソースコードは[Apache License 2.0](LICENSE)で提供します。
