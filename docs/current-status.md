# 現在の状態

- 更新日: 2026-09-26
- 配布版の記録: v0.5.1。2026-09-12の[配布・導入検証](verification/v0.5.1-release-2026-09-12.md)を参照
- 今回の変更: Workerの分類なし応答、条件付き取得、公開境界検査を修正し、不要な一時workflowと運用メモを削除
- 今回の変更はソースコードへ反映済み。Python packageの再配布とWeb deployは未実施
- R2、Worker、独自domain、外部検索indexは未公開。今回もWebの外部操作は実施していない

## 現行機能

Python API、CLI、stdio MCP、Codex・Claude Code用agent kit、決定的な公開export、Cloudflare Worker、OpenAPI、WebMCPを実装している。日本語を既定とし、英語へ切り替えられる。

SQLite schema v2と分類record 2.0は、IPCの基準日・指定version、FI改正の参照概念、出典lineage、関係ページング、分類・文書の文字列検索に対応する。PMGS原資料とSQLiteは配布物へ含めない。

## 今回の保守変更と検証

[2026-09-26の保守検証](verification/maintenance-2026-09-26.md)に、修正の再現条件、実測結果、削除対象、検証限界を記録する。

- 分類chunkの範囲内にある未収録コードは404を返す。manifest総件数・chunk件数・境界キー・順序・releaseの不整合は503で拒否する。
- R2直接配信のGET・HEADは、弱いETagを含む条件付き取得に対応する。
- 公開境界検査は作業ディレクトリによらずrepository全体を対象とする。生成物の強制追加、バイナリ・NUL入りファイル、リンク、端末固有pathの検査を強化した。
- 一時的な自動push workflowと、公開利用者に不要な依存更新PRの作業メモを削除した。

Pythonは355件合格・10件skip、LinuxのWorker・HTTPは73件、WebMCPは3件合格した。公開境界217候補、Ruff、mypy、wheel・sdist build、Worker dry-run build、依存監査、Markdownリンク検査にも合格した。skipはWindowsのsymlink権限とPOSIX専用条件による。Windows workerdの起動失敗などの限界は上記の保守検証記録へ記載した。

## GitHub source repositoryの公開検証

GitHub source、PyPI package、GitHub Releaseの公開履歴は、[v0.5.1](verification/v0.5.1-release-2026-09-12.md)と[v0.5.0](verification/v0.5-release-2026-08-24.md)の記録を参照する。これらは測定時点の証拠であり、今回の変更や現在の外部設定を検証した記録ではない。

## 残る検証と運用上の境界

- Claude Codeの設定・登録・skill・tool制限は自動検証済み。live MCP互換性は`not_observed`を維持する。
- schema v2の実データA/BとCodex実MCP評価は[v0.4.0の正確性検証](verification/v0.4-correctness-2026-08-12.md)を参照する。後日のvalidator変更へ自動的に合格を継承しない。
- 第三者がWeb公開する場合は、実originを使って現行契約のA/Bを新規生成し、全件validation・auditを実施する。手順は[release runbook](release-runbook.md)と[セルフホストガイド](self-hosting.md)を参照する。
- ローカル検証には実PMGSの再構築・全量A/B、macOS、GitHub hosted CI、外部配布・Web公開を含めていない。GitHubでの統合時は対象PRのchecksを別途確認する。

次のPython package公開では、tag付きrelease gateと公開artifactの配布検証が必要になる。
