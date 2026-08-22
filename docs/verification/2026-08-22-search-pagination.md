# Search pagination verification — 2026-08-22

対象PR: #36

## 変更対象

- 分類・文書検索で重複一致をページ上限適用前に集約する。
- 分類・文書を独立したoffsetでページングする。
- `has_more` / `next_offset`を返す。
- SQLiteのsigned 64-bit整数範囲を超えるoffsetを`INVALID_OFFSET`として拒否する。
- 日本語インターフェース文書の破損文字列を修正する。

## 回帰条件

- 同一分類・同一文書へ多数の一致行が集中しても別候補が欠落しない。
- 1ページ目と2ページ目で重複・欠落がない。
- FTS5経路と短語LIKE経路の両方を検証する。
- `2**63`のoffsetがSQLiteへ到達する前に構造化エラーになる。

## 検証状態

レビュー指摘を反映したcommit `a7016d602dcf3e4115a35646e16962cbb3ff2993`を基準に、GitHub Actionsの全必須チェックを実行する。この記録を追加したcommitのhosted CI結果を最終マージ判定に使用する。
