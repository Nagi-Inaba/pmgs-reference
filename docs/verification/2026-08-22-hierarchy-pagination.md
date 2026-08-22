# Hierarchy pagination verification — 2026-08-22

対象PR: #53  
対象Issue: #24

## 目的

親子階層の一覧取得を、各項目の完全な`lookup()`を繰り返すN+1経路から、決定的なbounded summaryのページングへ移行する。

## 契約

- `hierarchy(direction, scheme, code, limit, offset)`をページングの正本とする。
- `direction`は`parents`または`children`だけを許可する。
- 応答は`count`、`limit`、`offset`、`truncated`、`next_offset`を持つ。
- 各結果は`scheme`、`edition`、`code`、`version`、`label`、`record_status`だけを返す。
- 並び順を固定し、ページ間の重複・欠落を防ぐ。
- `parents()`と`children()`は、明示的な`limit`がある場合はページ応答を返し、省略時は互換性のため全ページを平坦化する。
- release基準日に複数revisionが同時にactiveな場合、先頭を推測で選ばず`MULTIPLE_ACTIVE_REVISIONS`でfail closedにする。

## 回帰テスト

`tests/test_hierarchy_pagination_contract.py`で次を検査する。

- 805件を追加した階層で200件ずつ取得できること。
- 一件ごとの`lookup()`を呼ばないこと。
- 1ページ目と2ページ目が重複しないこと。
- bounded summary以外のフィールドを返さないこと。
- 複数active revisionを安全に拒否すること。
- 既存の`parents()`と`children()`が互換結果を返すこと。

## focused verification

一時的なbranch内検証workflowで、実装適用後に次を実行し、成功した場合だけ実装commitを作成した。

- `ruff format`
- `ruff check`
- `mypy src`
- `pytest -q tests/test_hierarchy_pagination_contract.py tests/test_store.py`

## hosted CI

最新のユーザーcommitに対する通常CI matrixを最終マージ条件とする。全jobの結論、failure、skipはCI完了後にこの記録へ追記する。
