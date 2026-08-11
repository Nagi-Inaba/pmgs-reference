# 要件トレーサビリティ

## 状態の定義

`verified`は、現在の実装と要件を直接検証する証拠がある状態である。

`implemented`は、実装済みだが現在契約での最終検査が残る状態である。

`external`は、GitHubまたは本番環境での外部確認が必要な状態である。

## v1要件

| ID | 要件 | 状態 | 証拠または残作業 |
| --- | --- | --- | --- |
| DOC-01 | 設計、状態、判断、runbookを版管理する | verified | `PLAN.md`、`docs/current-status.md`、ADR、runbook |
| DATA-01 | 全入力をhash付きmanifestへ記録する | verified | 6,870 source、論理SHA-256を検証記録へ保存 |
| DATA-02 | 全入力を`parsed`、`retained`、`failed`で説明する | verified | parsed 6,868、retained 2、failed 0 |
| DATA-03 | CSV、XML、HTML、PDFを専用adapterで処理する | verified | 合成fixtureと実データprofile |
| DATA-04 | FI、Fターム、IPC、解説、改正、対応、定義文書をSQLiteへ格納する | verified | 1,207,960 concept、6,667 document、未表現source 0 |
| DATA-05 | 旧DBの既知件数を回帰基準にする | verified | Fタームテーマ2,929、Fターム411,383、FI 190,384、IPC 8U 82,540が一致 |
| STORE-01 | 版付きSQLiteとFTS5を生成する | verified | SQLite schema、FTS5 trigram、integrityと外部key検査 |
| STORE-02 | 内容アドレス付きSQLiteを保持し、検証済み現行版を原子的に切り替える | verified | `data_paths.py`、`setup.py`、setupの再利用・source変更・lock・legacy・pointer test、3 OS hosted CI |
| NORM-01 | PythonとTypeScriptが同じ正規化vectorを通す | verified | `schemas/normalization-vectors.json`と両実装のtest |
| API-01 | Python APIがlookup、search、階層、文書、release情報を提供する | verified | 合成fixture testと実データsmoke |
| CLI-01 | inventory、build、validate、lookup、search、document、doctor、agent kit、skill導入、mcpを提供する | verified | CLI test、agent kit test、実stdio protocol smoke |
| CLI-02 | export、公開検証、release auditを提供する | verified | 合成fixture testと2026-08-08の全量回帰記録 |
| CLI-03 | `pmgs setup`が全OSで構築、検証、切替、client接続を一つの入口から実行する | verified | setup CLI、JSON・対話契約、dry-run、Ubuntu・Windows・macOSのwheel E2E |
| MCP-01 | stdio MCPが三つの読み取り専用toolを提供する | verified | SDK tool testとstdio protocol smoke |
| AGENT-01 | CodexとClaude Codeへclient別MCP設定を生成する | verified | TOMLとJSONのparser test、登録command test |
| AGENT-02 | 同じ読み取り専用skillを両clientへ非破壊で導入する | verified | hash一致、冪等、上書き拒否、途中失敗回収、同時競合保持test |
| AGENT-03 | 実stdio接続とSQLite不変性を診断する | verified | `pmgs doctor`の実client、tool契約、hash不変test |
| AGENT-04 | 日本語を既定にし、英語へ切り替えられる | verified | CLI、skill、日英README、Web top、`llms.txt`のtest |
| AGENT-05 | client登録を管理ディレクトリ参照にし、同一設定を再利用して競合を上書きしない | verified | fake Codex・Claude Codeのargv、再利用、競合、部分失敗、`CLAUDE_CONFIG_DIR`、Windows batch安全性test、3 OS wheel E2E |
| DOC-02 | 第三者向けWebセルフホストとGPTs、Gem、Copilot Studioの制約を公開する | verified | 日英ガイドと全Markdown相対link test |
| PUB-01 | 公開分類をHTML、Markdown、JSONで生成する | verified | 現行の日英入口契約を合成fixtureで検証。実データは2026-08-09の直前契約で全件監査済みで、Web公開時に現行契約を再監査する |
| PUB-02 | 公開文書をHTML、Markdown、JSONで生成する | verified | 現行の日英入口契約を合成fixtureで検証。実データは2026-08-09の直前契約で全件監査済みで、Web公開時に現行契約を再監査する |
| PUB-03 | 元archive、正本DB、一括JSONを公開成果物へ含めない | verified | repository boundaryと公開validator |
| PUB-04 | OpenAPI、`llms.txt`、`robots.txt`、sitemapを生成する | verified | JSON、XML、HTML parser test |
| PUB-05 | 帰属、原典URL、加工表示、非公式サービス表示を全公開ページへ出す | verified | policy schema、21対象pytest、validatorの`notice_errors`反証test |
| PUB-06 | JSON sourceにowner、原典URL、attributionを含める | verified | classification schemaと公開record test |
| PUB-07 | v1で曖昧な複数source policyを拒否する | verified | schema `maxItems: 1`とfail-closed loader test |
| PUB-08 | 公開attributionを入力releaseの権利表示と一致させる | verified | SQLite `COPYRGHT`との事前照合と不一致反証test |
| WORKER-01 | Workerが版付きR2成果物を2 read以内で返す | verified | [Worker検証](verification/worker-2026-08-08.md)とworkerd test |
| WORKER-02 | APIが入力、CORS、404、503、security header契約を満たす | verified | workerd route test |
| WEBMCP-01 | 対応時だけlookup toolを一つ登録する | verified | TypeScript test、実対応browser smokeは任意外部確認 |
| RELEASE-01 | 合成fixtureでrepository全検査を通す | verified | pytest 98件、Ruff、mypy、boundary、sdist、wheelに合格 |
| RELEASE-02 | 実データのA/B buildと全件監査を通す | implemented | [2026-08-09の監査](verification/public-release-2026-08-09.md)は当時の契約で`ready=true`。2026-08-10の日英入口追加後はWeb公開時に再監査する |
| RELEASE-03 | build、test、typecheck、lint、Worker bundleを再現する | verified | Python標準検査とWorker `verify`に合格 |
| RELEASE-04 | wheelを3 OSで隔離導入し、setup、再実行、doctorを検証する | verified | [Hosted CI run 31506514581](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31506514581)の3 OS `wheel-e2e` job |
| RELEASE-05 | tag、承認環境、Trusted Publishing、attestationでPyPIとGitHub Releaseへ同じ成果物を配布する | implemented | SHA固定の`release.yml`。GitHub `pypi`環境、PyPI pending publisher、tag実行は外部設定待ち |
| GH-01 | 追跡対象と公開履歴に実データ、生成DB、秘密情報、端末固有pathがない | verified | 公開境界guardと単一rootの公開用履歴を検査 |
| GH-02 | CIを最小権限、SHA固定、credential非保持、timeout付きで定義する | verified | [v0.3.0 branch CI run 31506514581](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31506514581)で10 jobが成功。mainの必須check更新は外部設定待ち |
| GH-03 | contribution、security、Issue、PRのdata-safeな受付境界を定義する | verified | `CONTRIBUTING.md`、`SECURITY.md`、Issue forms、PR template、CODEOWNERS |
| GH-04 | 公開用Git履歴から旧版の公開対象外運用記録を除去する | verified | clean root commit `c3f836b`から公開履歴を開始し、旧履歴を外部backupへ分離 |
| GH-05 | hosted check、Security設定、ruleset、public visibilityを確認する | verified | [現在のGitHub公開検証](current-status.md#github-source-repositoryの公開検証)と[GitHub公開チェックリスト](github-publication-checklist.md) |

## v1対象外

AI要約、機械翻訳、意味検索、D1、Vectorize、Workers AI、Remote MCP、SPARQL、自動Web公開はv1要件に含めない。

GitHub source repositoryを現在の配布面とする。R2 upload、Worker deploy、domain設定、PyPI公開、外部indexは別の外部releaseとして記録する。Python packageの公開経路は実装したが、tagと承認を通過するまでは`published`としない。
