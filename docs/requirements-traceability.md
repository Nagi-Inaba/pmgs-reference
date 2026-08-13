# 要件トレーサビリティ

## 状態の定義

`verified`は、現在の実装と要件を直接検証する証拠がある状態である。

`implemented`は、実装済みだが現在契約での最終検査が残る状態である。

`external`は、GitHubまたは本番環境での外部確認が必要な状態である。

`hold`は、旧契約の証拠はあるが、現在開発中のschemaまたはinterface契約での再検証が必要な状態である。

`not_observed`は、必要な外部アカウントまたは実環境を利用できずlive挙動を確認していない状態である。自動試験の成功をlive成功へ読み替えない。

## v1要件

| ID | 要件 | 状態 | 証拠または残作業 |
| --- | --- | --- | --- |
| DOC-01 | 設計、状態、判断、runbookを版管理する | verified | `PLAN.md`、`docs/current-status.md`、ADR、runbook |
| DATA-01 | 全入力をhash付きmanifestへ記録する | verified | 6,870 source、論理SHA-256を検証記録へ保存 |
| DATA-02 | 全入力を`parsed`、`retained`、`failed`で説明する | verified | parsed 6,868、retained 2、failed 0 |
| DATA-03 | CSV、XML、HTML、PDFを専用adapterで処理する | verified | 合成fixtureと実データprofile |
| DATA-04 | FI、Fターム、IPC、解説、改正、対応、定義文書をSQLiteへ格納する | verified | schema v2候補Aの全量54チェックでIPC revision 84,195件、FI改正関係39,428件、未解決endpoint 0件を確認 |
| DATA-05 | 旧DBの既知件数を回帰基準にする | verified | Fタームテーマ2,929、Fターム411,383、FI 190,384、IPC 8U 82,540が一致 |
| STORE-01 | 版付きSQLiteとFTS5を生成する | verified | schema v2候補AでSQLite integrity、FTS parity、lineage、logical digestを含む54チェックに合格 |
| STORE-02 | 内容アドレス付きSQLiteを保持し、検証済み現行版を原子的に切り替える | verified | `data_paths.py`、`setup.py`、setupの再利用・source変更・lock・legacy・pointer・出力競合test、Windowsの実exFAT構築。現行commitの3 OS hosted CIは`RELEASE-04`で追跡する |
| NORM-01 | PythonとTypeScriptが同じ正規化vectorを通す | verified | `schemas/normalization-vectors.json`と両実装のtest |
| API-01 | Python APIがlookup、search、階層、文書、release情報を提供する | verified | IPC基準日版・明示版・無効版、relation pagination、分類・文書分離検索の合成回帰と実データsmokeに合格 |
| CLI-01 | inventory、build、validate、lookup、search、document、doctor、agent kit、skill導入、mcpを提供する | verified | CLI test、agent kit test、実stdio protocol smoke |
| CLI-02 | export、公開検証、release auditを提供する | verified | 合成fixture testと最終実データA/B各454,303 objectの全件validation、25条件release audit |
| CLI-03 | `pmgs setup`が全OSで構築、検証、切替、client接続を一つの入口から実行する | verified | setup CLI、JSON・対話契約、dry-run、Ubuntu・Windows・macOSのwheel E2E |
| MCP-01 | stdio MCPが三つの読み取り専用toolを提供する | verified | typed input、protocol error、version、複合検索、prompt injection境界の回帰とCodex実MCP評価に合格 |
| AGENT-01 | CodexとClaude Codeへclient別MCP設定を生成する | verified | TOMLとJSONのparser test、登録command test |
| AGENT-02 | 同じ読み取り専用skillを両clientへ非破壊で導入する | verified | hash一致、冪等、上書き拒否、途中失敗回収、同時競合保持test |
| AGENT-03 | 実stdio接続とSQLite不変性を診断する | verified | `pmgs doctor`の実client、tool契約、照会前後hash、managed pointer SHA不一致と診断中pointer切替の拒否test |
| AGENT-04 | 日本語を既定にし、英語へ切り替えられる | verified | CLI、skill、日英README、Web top、`llms.txt`のtest |
| AGENT-05 | client登録を管理ディレクトリ参照にし、同一設定を再利用して競合を上書きしない | verified | fake Codex・Claude Codeのargv、再利用、競合、部分失敗、`CLAUDE_CONFIG_DIR`、Windows batch安全性test、3 OS wheel E2E |
| AGENT-06 | Codexが読み取り専用MCPを使い、取得本文を命令として実行しない | verified | 隔離wheelの全10ケースに合格し、禁止tool呼出し0件を機械判定 |
| AGENT-07 | Claude Codeが読み取り専用MCPを使い、取得本文を命令として実行しない | not_observed | 設定、skill、分離環境、tool制限は自動検証済み。現在利用できる無料アカウントでは評価に必要なClaudeモデル呼出しを実行できないため、修正後のlive MCP評価は未観測。ユーザー承認によりsource統合の阻害条件から外し、Claude live互換性の成功は主張しない |
| AGENT-08 | PMGS保有者とAIがinstall、dry-run、setup、doctor、lookupを安全に開始できる | verified | 日英READMEと導入ガイドの機械可読契約、展開済みdirectory・容量・client分岐、archive拒否、MCP tool descriptionと配布skillの非アップロード・取得本文境界を回帰testで検証 |
| DOC-02 | 第三者向けWebセルフホストとGPTs、Gem、Copilot Studioの制約を公開する | verified | 日英ガイドと全Markdown相対link test |
| PUB-01 | 公開分類をHTML、Markdown、JSONで生成する | verified | classification record 2.0とrevision bundleを実データA/B各454,303 objectで最終validatorにより全件再検証し、全error群0、tree SHA-256一致 |
| PUB-02 | 公開文書をHTML、Markdown、JSONで生成する | verified | 現行の日英入口契約を合成fixtureで検証し、分類と文書を含む最終実データA/B公開treeを全件validation |
| PUB-03 | 元archive、正本DB、一括JSONを公開成果物へ含めない | verified | repository boundaryと公開validator |
| PUB-04 | OpenAPI、`llms.txt`、`robots.txt`、sitemapを生成する | verified | JSON、XML、HTML parser test |
| PUB-05 | 帰属、原典URL、加工表示、非公式サービス表示を全公開ページへ出す | verified | policy schema、21対象pytest、validatorの`notice_errors`反証test |
| PUB-06 | JSON sourceにowner、原典URL、attributionを含める | verified | classification schemaと公開record test |
| PUB-07 | v1で曖昧な複数source policyを拒否する | verified | schema `maxItems: 1`とfail-closed loader test |
| PUB-08 | 公開attributionを入力releaseの権利表示と一致させる | verified | DB由来のowner、URL、COPYRGHTとpolicyをA/B export前に完全一致で照合し、全公開notice error 0 |
| WORKER-01 | Workerが版付きR2成果物を2 read以内で返す | verified | [Worker検証](verification/worker-2026-08-08.md)とworkerd test |
| WORKER-02 | APIが入力、CORS、404、503、security header契約を満たす | verified | workerd route test |
| WEBMCP-01 | 対応時だけlookup toolを一つ登録する | verified | TypeScript test、実対応browser smokeは任意外部確認 |
| RELEASE-01 | 合成fixtureでrepository全検査を通す | verified | pytest 221件、Ruff、mypy、boundary、合成A/B決定性、sdist、wheelに合格。Windowsで権限上skipしたsymlink 7件はhosted CIでも検証する |
| RELEASE-02 | 実データのA/B buildと全件監査を通す | verified | 最終コードでNTFSとexFATへ独立再構築したSQLite A/Bのdatabase・build report・validation reportがbytesとSHA-256まで一致。公開tree A/Bも最終validatorと25条件release auditに合格 |
| RELEASE-03 | build、test、typecheck、lint、Worker bundleを再現する | verified | 最終コードでPython標準検査、二重package build、隔離wheel、Worker 31件とWebMCP 3件に合格 |
| RELEASE-04 | wheelを3 OSで隔離導入し、setup、再実行、doctorを検証する | verified | commit `4ec6738`の[Pull Request CI run 31634407211](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634407211)でUbuntu、Windows、macOSのwheel E2Eと3 OS合成決定性比較を含む14 jobが成功 |
| RELEASE-05 | tag、承認環境、Trusted Publishing、attestationでPyPIとGitHub Releaseへ同じ成果物を配布する | implemented | SHA固定の`release.yml`。GitHub `pypi`環境はrequired reviewerと`v*` tag制限を設定し、PyPI pending publisherも同じowner、repository、workflow、environmentで登録済み。tag実行と公開後の外部検証が残る |
| GH-01 | 追跡対象と公開履歴に実データ、生成DB、秘密情報、端末固有pathがない | verified | 公開境界guardと単一rootの公開用履歴を検査 |
| GH-02 | CIを最小権限、SHA固定、credential非保持、timeout付きで定義する | verified | commit `4ec6738`の[Push CI run 31634401819](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634401819)と[Pull Request CI run 31634407211](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634407211)で各14 jobが成功。既存10 checkはbranch protectionで必須、追加の決定性4 jobもPR統合ゲートとして確認 |
| GH-03 | contribution、security、Issue、PRのdata-safeな受付境界を定義する | verified | `CONTRIBUTING.md`、`SECURITY.md`、Issue forms、PR template、CODEOWNERS |
| GH-04 | 公開用Git履歴から旧版の公開対象外運用記録を除去する | verified | clean root commit `c3f836b`から公開履歴を開始し、旧履歴を外部backupへ分離 |
| GH-05 | hosted check、Security設定、ruleset、public visibilityを確認する | verified | commit `4ec6738`の[CodeQL run 31634403653](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634403653)でActions、Python、JavaScript/TypeScriptが成功。ほかは[現在のGitHub公開検証](current-status.md#github-source-repositoryの公開検証)を参照 |
| GH-06 | review済みsourceをmainへ統合し、mainのhosted checksを確認する | verified | [Pull Request #6](https://github.com/Nagi-Inaba/pmgs-reference/pull/6)をcommit `19ab5e1`へsquash merge。[Main CI run 31662197654](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31662197654)の14 jobと[Main CodeQL run 31662197622](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31662197622)の3解析が成功 |

## v1対象外

AI要約、機械翻訳、意味検索、D1、Vectorize、Workers AI、Remote MCP、SPARQL、自動Web公開はv1要件に含めない。

GitHub source repositoryを現在の配布面とする。R2 upload、Worker deploy、domain設定、PyPI公開、外部indexは別の外部releaseとして記録する。Python packageの公開経路は実装したが、tagと承認を通過するまでは`published`としない。
