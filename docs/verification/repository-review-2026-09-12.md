# 全体レビューとテスト整理（2026-09-12）

Pythonの取込・検索・setup・CLI・MCP・公開export、Workerの配信経路、テスト構成をレビューし、再現できた不具合を修正した。変更はローカルの改修であり、公開済みv0.5.0の配布物やWeb運用状態には反映していない。

## 修正内容

| 対象 | 確認した問題と修正 |
| --- | --- |
| Python照会 | 小数・bool・SQLite整数範囲外のページ指定を統一検証し、内部例外や意図しない受理を防ぐ。空の`content_types`は明示的に拒否する |
| Worker文書API | 未対応schema、metadata欠落、不正な格納先を503で拒否する。正常応答の最大2回のR2読込を維持する |
| 公開validator | JSONが読めてhashが一致していても、不正な分類・文書レコードやmanifest参照を拒否する。件数、範囲、ページ、bytes、SHA-256を実ファイルの要約と照合する |
| 公開監査 | A/B両treeを再検証する。保存済みreportが正常でも、その後に変更された成果物を公開可能と判定しない |
| DB設置 | 排他的hard linkの成功後、一時名の削除がPermissionErrorになっても、設置済みDBをbuild失敗と報告しない。一時名が残る場合はある |
| 公開policy | YAML入力と公開JSONの検証を共通化し、存在しない暦日を拒否する |

公開validatorは既存の`parse_errors`と`coverage_errors`へ不合格理由を記録する。CLIの引数、公開schema版、依存package、生成する正常成果物の形式は変更していない。新しい契約検査はPython package内に含まれ、開発用JSON Schemaライブラリには依存しない。

## テスト整理

重複または固定文言に依存した12本を削除・統合した。固有の検証は残存テストへ移した。

| 削除・統合対象 | 残した検証 |
| --- | --- |
| v0.5.0公開文言の固定テスト2本 | 現在のpackage versionとrelease tagの一致、Markdownリンク検査 |
| release gateの重複・runbook文言3本 | 解析したworkflowの依存関係、distribution検査、Worker検査 |
| 正常FTS検査2本 | build検証にschema、整合性、parity、tokenizer、DB前後hashを統合 |
| MCP stdio smoke 1本 | doctorの実stdio接続と3 tool呼出し |
| 同一processのsetup lock 1本 | 別processの排他、エラー内容、解放後の再取得 |
| Worker helper・固定binding 2本 | HTTP/R2の統合テスト |
| wheel検証scriptの固定文字列1本 | 実行結果と動的package versionの検査 |

通常のWorkerテストから250ms未満という時間条件を削除した。大きなchunkの結果と2回の読込上限は維持し、専用benchmarkは残した。再現した不具合に対してPython 3本とWorker 1本を追加し、テスト定義は差引8本減らした。公開validatorの追加テストは11種類、Workerの追加テストは4種類の破損を一つの関連テスト内で確認する。

## 検証範囲と限界

| 検証 | 結果 |
| --- | --- |
| `uv lock --check` | 合格 |
| repository boundary | 214候補、合格 |
| Ruff lint / format、mypy | 合格。型検査32 module |
| Python全体 | 338 passed / 9 skipped。修正前は345 passed / 9 skipped |
| 最後の日付・格納group修正後の公開テスト | 52 passed / 4 skipped |
| wheel・sdist build | 合格 |
| 隔離wheel導入 | 初回setup=`ready`、再実行=`already_ready`、doctor成功、lookup=`exact`、MCP 3 tool成功 |
| Windows Worker | 依存導入、bindings、型検査、lint、build、WebMCP 3件、npm audit合格。Cloudflare runner起動はtimeout |
| Linux Worker | `npm ci && npm run verify`合格。Worker 45件、WebMCP 3件、npm audit 0件 |
| 最終コードの合成A/B | 各103 object・252,605 bytes、12分類group・8文書。両validation一致・合格、監査25条件すべて合格 |
| 文書リンク・差分 | Markdown相対リンク検査、`git diff --check`合格 |

独立レビューでは公開境界、取込、validationの問題を確認し、限定再レビューで残った日付と格納groupの不足も修正した。該当回帰を追加し、公開テスト52件で確認した。公開の11破損ケースでは、objectと内部manifestのhashを更新しても不合格になることを検証している。

最終コードで追跡済み合成入力`JPPM2099001`から新しいDBとA/Bを生成した。両exportのtree SHA-256は`30C5430522C79FF6E1DB872B46E1A240F318D4F53F3BA765477B0523E4EC3D32`、release manifest SHA-256は`F3210C5A9787659E14ABE4EF596EC04C438BD52A6A7CC8F9F6D651497B0E8810`で一致した。oversized chunkは0件、監査は`ready=true`・`failures=[]`だった。

WindowsのCloudflare test runnerは起動待ち90秒でtimeoutし、テストを実行できなかった。同じWorkerソースとlockfileをLinuxのNode 22.19.0コンテナへコピーして検証した。Windowsのsymlink権限とPOSIX専用条件によるskipは残す。実PMGSの再構築・全量A/B再監査、macOSでの実行、GitHub CI、外部公開は今回の検証に含めない。
