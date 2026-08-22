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

## Hosted CI evidence

レビュー指摘を反映したコードと初版の本検証記録を含むcommit `285a45bb474a2ad2826c6f75e4d6b31f80218820`を、GitHub Actions CI run `32565932960`（run #233）で検証した。

- Python 3.12 / 3.14: Ubuntu、Windows、macOSの全jobが成功。
- Installed wheel: Ubuntu、Windows、macOSの全jobが成功。
- Synthetic determinism: Ubuntu、Windows、macOSとcross-OS compareが成功。
- Cloudflare Worker on Node 22が成功。
- Ubuntu / Python 3.12のfull pytestは`245 passed, 5 skipped in 27.28s`。
- skipはWindows専用契約・Windows command lookup・Windows cmd.exe integration・Windows junction coverageの5件で、対象の検索ページング経路ではない。
- repository boundary: 178 candidate files、違反なし。
- Ruff check、Ruff format check、mypyが成功。
- wheelとsdistのbuildが成功。
- CI failure: 0。

この後のcommitは上記測定結果を記録する文書変更のみであり、production codeおよび回帰testは変更しない。最終マージ前に、この文書変更を含むheadでも必須CIを再実行する。
