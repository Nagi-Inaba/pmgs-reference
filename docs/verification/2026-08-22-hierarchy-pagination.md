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
- `canonical`と`reference_only`の双方を、保存されたrelationどおりに返す。
- 並び順を固定し、ページ間の重複・欠落を防ぐ。
- `parents()`と`children()`は、明示的な`limit`がある場合はページ応答を返し、省略時は互換性のため全ページを平坦化する。
- release基準日に複数revisionが同時にactiveな場合、先頭を推測で選ばず`MULTIPLE_ACTIVE_REVISIONS`でfail closedにする。

## 回帰テスト

`tests/test_hierarchy_pagination_contract.py`で次を検査する。

- 805件を追加した階層で200件ずつ取得できること。
- 一件ごとの`lookup()`を呼ばないこと。
- 1ページ目と2ページ目が重複しないこと。
- bounded summary以外のフィールドを返さないこと。
- `reference_only`のrelationが脱落しないこと。
- 複数active revisionを安全に拒否すること。
- 既存の`parents()`と`children()`が互換結果を返すこと。

## REDと修正

最新`main`から再構成した最初のCI run `32581853823`では、旧PRの`store.py`が既存の検索ページング引数`classification_offset`と`document_offset`を巻き戻しており、mypyとwheel E2Eが失敗した。このため、`store.py`を最新`main`へ戻したうえで、階層部分だけを差分適用した。

回帰テストでは、複数active revisionが存在する場合に階層一覧が先頭revisionを暗黙選択する欠陥もREDとして確認した。対象conceptを集約し、active revisionが2件以上なら`MULTIPLE_ACTIVE_REVISIONS`を返すよう修正した。

全CI成功後のコード差分レビューでは、階層SQLが`record_status = 'canonical'`で絞っており、旧APIが返していた`reference_only`の親子relationを落とすことを検出した。専用fixtureでREDを固定し、count・ambiguity check・page queryの対象を保存された全relationへ戻した。

## focused verification

一時的なbranch内検証workflowで、実装適用後および`reference_only`修正後に次を実行し、成功した場合だけ実装commitを作成した。

- `ruff format`
- `ruff check`
- `mypy src`
- `pytest -q tests/test_hierarchy_pagination_contract.py tests/test_store.py`

## hosted CI evidence

ユーザーcommit `195626d09b80fd6863edc2384c8eaea08c1e69bc`をGitHub Actions CI run `32582091811`（run #330）で検証し、全jobが成功した。

### Ubuntu Python 3.12

- repository boundary: 192 candidate files、違反なし
- Ruff check: success
- Ruff format check: `108 files already formatted`
- mypy: `Success: no issues found in 29 source files`
- pytest: `269 passed, 5 skipped in 43.06s`
- wheel / sdist build: success

skip 5件はWindows固有の既存契約であり、本変更固有のfailureまたはskipは0件だった。

### Full matrix

次を含むrun #330の全jobが成功した。

- Python 3.12 / 3.14 on Ubuntu、Windows、macOS
- Python 3.13 on Ubuntu
- installed wheel on Ubuntu、Windows、macOS
- installed wheel on Python 3.13
- Cloudflare Worker on Node 22
- synthetic determinism on Ubuntu、Windows、macOSとcross-OS compare

## 文書差分レビュー

全CI成功後の日英文書レビューで、旧PR由来の文書が次の既存契約を巻き戻していることを検出した。

- 検索結果の`classification_offset` / `document_offset`
- `pmgs doctor --timeout-seconds`
- `MCP_TIMEOUT`と診断reportの秘匿境界

日英文書を最新`main`へ戻し、階層APIの記述だけを追加した。保持すべき4項目が両文書に残ることを自動確認した。

## 最終ゲート

`reference_only`修正、文書修正、本検証記録を含む最新ユーザーcommitに対する通常CI matrixの全成功、未解決review threadがないこと、および最終差分レビューをマージ条件とする。
