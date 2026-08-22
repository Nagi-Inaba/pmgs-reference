# Worker HTTP contract verification — 2026-08-22

対象PR: #38

## 検証対象

- `Accept`のmedia range、wildcard、quality valueを解釈する。
- `q=0`を選択対象から除外する。
- `q`より前のmedia parameterを表現選択条件として照合する。
- `q`より後のaccept extensionを表現選択条件にしない。
- UTF-8 charset parameterを生成表現と照合する。
- APIと非API routeで実装済みmethodだけを`Allow`に返す。
- helper testがWorkerの通常verifyに実際に含まれる。

## 期待する回帰条件

- `text/html;level=1;q=1, text/markdown;q=0.5`は、`level=1`を持たないHTMLではなくMarkdownを選ぶ。
- `text/html;charset=UTF-8;q=1, text/markdown;q=0.5`はHTMLを選ぶ。
- `text/html;q=0;level=1, text/markdown;q=0.5`では`level=1`をaccept extensionとして扱いMarkdownを選ぶ。
- HTMLとMarkdownがともに`q=0`、または対応外media typeだけの場合は互換契約としてHTMLへfallbackする。
- API routeの`Allow`は`GET, HEAD, OPTIONS`、通常page routeは`GET, HEAD`とする。

## 検証状態

上記の実装・回帰test・ADRを含むheadに対してGitHub Actionsの全必須checkを実行し、最終マージ判定に使用する。完了したhosted CIのrun ID、test count、failure、skipをこの記録へ追記する。
