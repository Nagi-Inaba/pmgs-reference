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
| NORM-01 | PythonとTypeScriptが同じ正規化vectorを通す | verified | `schemas/normalization-vectors.json`と両実装のtest |
| API-01 | Python APIがlookup、search、階層、文書、release情報を提供する | verified | 合成fixture testと実データsmoke |
| CLI-01 | inventory、build、validate、lookup、search、document、mcpを提供する | verified | CLI testとstdio protocol smoke |
| CLI-02 | export、公開検証、release auditを提供する | verified | 合成fixture testと2026-08-08の全量回帰記録 |
| MCP-01 | stdio MCPが三つの読み取り専用toolを提供する | verified | SDK tool testとstdio protocol smoke |
| PUB-01 | 公開分類をHTML、Markdown、JSONで生成する | verified | 新表示契約の実データA/B各399,025 objectと全件validatorが合格 |
| PUB-02 | 公開文書をHTML、Markdown、JSONで生成する | verified | 新表示契約の実データA/B各399,025 objectと全件validatorが合格 |
| PUB-03 | 元archive、正本DB、一括JSONを公開成果物へ含めない | verified | repository boundaryと公開validator |
| PUB-04 | OpenAPI、`llms.txt`、`robots.txt`、sitemapを生成する | verified | JSON、XML、HTML parser test |
| PUB-05 | 帰属、原典URL、加工表示、非公式サービス表示を全公開ページへ出す | verified | policy schema、21対象pytest、validatorの`notice_errors`反証test |
| PUB-06 | JSON sourceにowner、原典URL、attributionを含める | verified | classification schemaと公開record test |
| PUB-07 | v1で曖昧な複数source policyを拒否する | verified | schema `maxItems: 1`とfail-closed loader test |
| PUB-08 | 公開attributionを入力releaseの権利表示と一致させる | verified | SQLite `COPYRGHT`との事前照合と不一致反証test |
| WORKER-01 | Workerが版付きR2成果物を2 read以内で返す | verified | [Worker検証](verification/worker-2026-08-08.md)とworkerd test |
| WORKER-02 | APIが入力、CORS、404、503、security header契約を満たす | verified | workerd route test |
| WEBMCP-01 | 対応時だけlookup toolを一つ登録する | verified | TypeScript test、実対応browser smokeは任意外部確認 |
| RELEASE-01 | 合成fixtureでrepository全検査を通す | verified | pytest 46件、Ruff、mypy、boundary、sdist、wheelに合格 |
| RELEASE-02 | 実データのA/B buildと全件監査を通す | verified | [2026-08-09の実データ公開候補検証](verification/public-release-2026-08-09.md)で`ready=true`、失敗0件 |
| RELEASE-03 | build、test、typecheck、lint、Worker bundleを再現する | verified | Python標準検査とWorker `verify`に合格 |
| GH-01 | 追跡対象と公開履歴に実データ、生成DB、秘密情報、端末固有pathがない | verified | 公開境界guardと単一rootの公開用履歴を検査 |
| GH-02 | CIを最小権限、SHA固定、credential非保持、timeout付きで定義する | verified | [Hosted CI run 31305434936](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31305434936)で5 jobが成功 |
| GH-03 | contribution、security、Issue、PRのdata-safeな受付境界を定義する | verified | `CONTRIBUTING.md`、`SECURITY.md`、Issue forms、PR template、CODEOWNERS |
| GH-04 | 公開用Git履歴から旧版の公開対象外運用記録を除去する | verified | clean root commit `c3f836b`から公開履歴を開始し、旧履歴を外部backupへ分離 |
| GH-05 | hosted check、Security設定、ruleset、public visibilityを確認する | verified | [現在のGitHub公開検証](current-status.md#github-source-repositoryの公開検証)と[GitHub公開チェックリスト](github-publication-checklist.md) |

## v1対象外

AI要約、機械翻訳、意味検索、D1、Vectorize、Workers AI、Remote MCP、SPARQL、自動公開はv1要件に含めない。

GitHub source repositoryの公開は完了した。R2 upload、Worker deploy、domain設定、PyPI公開、外部indexは別の外部releaseとして記録する。
