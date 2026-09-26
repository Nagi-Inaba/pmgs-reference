# 保守検証（2026-09-26）

## 変更

- 分類chunkの範囲内にある未収録コードが503になる不具合を404へ修正した。件数、両端キー、順序、release、lookup keyの不整合は503で拒否する。
- R2直接配信のGET・HEADで弱いETagを照合し、一致時は304を返す。表現ごとのETag、Vary、読込回数を維持する。
- repository境界検査の基準をscriptのrepository rootへ固定し、生成物の強制追加、NUL・バイナリ、リンク、Windowsの両区切り文字の絶対pathを拒否する。

## 公開物の整理

- `.github/workflows/repair-release-gates-sdist.yml`を削除した。過去の特定ブランチへ書き込む一時workflowであり、参照先の補助workflowとstaging断片は存在しない。
- 依存更新PRごとの判断・操作経過を記した運用メモを削除した。公開リリースの検証証拠は既存のrelease記録へ残す。
- `docs/current-status.md`と`PLAN.md`から重複する作業経過・個別承認・アカウント事情を除き、機能、配布状態、検証限界、次の作業へ整理した。
- 削除・整理前の原文はGit管理外のローカル保管先へコピーし、SHA-256一致を確認した。JPO証跡PDF・抽出本文、実データ、Git公開履歴は変更していない。

## ローカル検証

署名を確認したWindows CPython 3.14.3と既存の仮想環境を使用した。`pyvenv.cfg`の参照先も確認した。

| 検査 | 結果 |
| --- | --- |
| `uv lock --check` | 合格 |
| `uv run --frozen python scripts/verify_repository_boundary.py` | 217候補、合格 |
| `uv run --frozen ruff check .` / `ruff format --check .` | 合格。133 fileを整形確認 |
| `uv run --frozen mypy src` | 32 module、合格 |
| `uv run --frozen pytest -q` | 355 passed / 10 skipped、120.85秒。skipはWindowsのsymlink権限9件とPOSIX専用条件1件 |
| 境界検査・project契約の最終変更後の重点検査 | 30 passed / 1 skipped。Markdownリンク、JSON Schema、YAML・TOML契約を含む |
| `uv build` | wheel・sdistの構築に成功 |
| Linuxで`npm --prefix worker ci`、`npm --prefix worker run verify` | bindings、型検査、lint、Worker・HTTP 73件、WebMCP 3件、dry-run build、依存監査に合格。脆弱性0件 |
| `git diff --check` / staged差分検査 | 合格 |

Workerは、作業中のWorker・schemaファイルだけを隔離コピーし、既存のNode.js 22.19.0 Linuxコンテナで検証した。検証用コピーと作業ツリーの全対象fileのSHA-256一致を確認した。元のWindows workerdはsocket listenがエラー10013で拒否され、テスト起動に失敗した。Linuxの成功をWindows実行成功とは扱わない。

修正前には、R2代替を使うNode.js検証で、未収録コードが503、弱いETagのGET・HEADが200となることを再現した。修正後は404・304となり、分類照会2 read、条件付き取得1 readを維持した。Linux workerdでも同じ回帰と破損chunkの503を確認した。

重点pytestではWindowsのnative `access violation`診断がstderrへ出たが、processは終了code 0、30件合格で完了した。診断は隠しておらず、原因は未特定である。最終の全体pytestは355件合格し、この診断は0件だった。WorkerではR2 streamの`pump canceled`診断が出たが、全64件と後続gateは合格した。

## 検証対象外

このローカル検証には、実PMGS再構築、全量A/B、macOS、hosted CI、Git履歴・staging blobの全内容監査、外部配布・Web公開を含めていない。SQLite・export schema・公開成果物の生成処理には変更がない。

## マージ前レビュー

`If-None-Match`に一致するタグと不正な後続文字が含まれると304になることを再現した。ヘッダー全体をタグ一覧として検証し、不正な一覧は一致なしとして通常の200応答にするよう修正した。引用符内のカンマ、弱いタグ、空の一覧要素は引き続き受け付ける。分類chunkの不整合拒否、公開境界、削除対象の参照関係も確認した。

追加した7ケースとGET・HEADの回帰を含むレビュー時点のLinux検証は71件・WebMCP 3件に合格した。初回は既存の`beforeAll`でR2 fixtureの準備が10秒の制限に達して失敗したが、同じsourceと設定の再実行は全gateに合格した。timeout設定やテストの省略条件は変更していない。

[PR #84](https://github.com/Nagi-Inaba/pmgs-reference/pull/84)の自動レビューで、manifest総件数と全chunk entryの件数合計の照合不足が見つかった。総件数だけの変更と照会対象外chunk entryの件数変更を再現し、既存code・範囲内の未収録code・範囲外codeの全6通りを、chunk探索前に503で拒否するよう修正した。R2代替による検証では、不整合時の読み取りは1回だった。

追加した2テストを含む修正後のLinux `npm ci` / `npm run verify`は、Worker・HTTP 73件、WebMCP 3件、bindings、型検査、lint、build、依存監査0件に合格した。公開境界217候補とMarkdownリンクも再検証した。
