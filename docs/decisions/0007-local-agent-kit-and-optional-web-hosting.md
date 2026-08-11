# ADR 0007: ローカルAIエージェント配布を既定にする

- 状態: 採用
- 日付: 2026-08-10

## 文脈

CodexとClaude Codeの利用者は、Python packageとstdio MCPをローカルで使える。

一方、GPTs、Gem、Copilot Studioから全量PMGSを参照させるには、公開Web成果物の保存、Worker、domain、検索index、継続運用が必要になる。

2026-08-09に監査した直前契約の全量候補は399,025 object、10,491,136,463 bytesであり、公開後はstorage、operation、Worker、domain、監視の費用と運用責任が生じる。日英入口追加後の現行契約は、Web公開時に実originで再計測する。

Knowledge fileへの全量投入は規模に合わず、一般的なGemへ任意OpenAPIを直接登録できるとも限らない。Copilot StudioもtenantごとにOpenAPI版とconnector policyが異なる。

## 決定

現在の公式配布はGitHub source repositoryとローカルAIエージェントkitを中心にする。

ローカルkitは次を含む。

- Codex用`config.toml`断片
- Claude Code用`.mcp.json`
- 両clientで共有する`pmgs-reference` skill
- 実stdio接続とSQLite不変性を検査する`pmgs doctor`
- 設定、skill、登録commandを生成する`pmgs agent-kit`
- skillを非破壊で導入する`pmgs install-agent-skill`
- Windowsで棚卸しから導入まで行う`setup_local_agent.ps1`
- AIが分類を推測しないことを検査する評価ケース

2026-08-11のv0.3設計では、上記の個別commandとagent kitを互換面として維持しつつ、全OS共通の`pmgs setup`を既定の導入口にした。版付きDB、原子的な現行版切替、client登録の詳細は[ADR 0008](0008-transactional-local-setup.md)に定める。Windows scriptは`pmgs setup`へ引数を渡す薄いadapterとする。

日本語をREADME、skill、説明、検索応答、公開ページの既定言語とする。英語は`README.en.md`、英語版ガイド、`language=en`、`/en/`で選択できる状態を維持する。

Web実装は削除しない。第三者が自分のdata、account、domain、予算で運用できるよう、セルフホスト手順とGPTs、Gem、Copilot Studioの互換性境界を公開する。

本リポジトリの管理者は、別の外部判断が行われるまでR2 upload、Worker deploy、domain接続を実施しない。

## 結果

CodexとClaude Codeの利用者は、公開Web serviceへPMGS本文を送らずに同じSQLite正本を参照できる。

クライアント固有の設定形式は別々に生成し、分類照会の手順だけを共通skillとして共有できる。

Web公開費用を本リポジトリの継続条件にせず、第三者による公開可能性は残る。

GPTsとGemのWeb参照はbest effortであり、検索indexや特定domainの使用を保証しない。

OpenAPI 3.1を受け付けないCopilot Studio環境では、Power Platform互換定義を別途生成して検証する必要がある。

## 不採用案

全量PMGSを各AI製品のKnowledgeへ同梱する案は、容量、更新、版管理、出典追跡を各clientで重複させるため採用しない。

Web公開をローカル利用より先に必須化する案は、費用と外部運用をsource distributionの前提にするため採用しない。

CodexとClaude Codeへ同じ設定fileを配る案は、TOMLとJSON、scope、承認モデルが異なるため採用しない。

一般的なGemがOpenAPIを直接利用できると仮定する案と、Copilot StudioがOpenAPI 3.1を必ず受け付けると仮定する案は、現行の公式手順で保証できないため採用しない。
