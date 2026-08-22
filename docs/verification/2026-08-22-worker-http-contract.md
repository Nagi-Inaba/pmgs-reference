# Worker HTTP contract verification — 2026-08-22

対象PR: #38

## 検証対象

- `Accept`のmedia range、wildcard、quality valueを解釈する。
- `q=0`を選択対象から除外する。
- `q`より前のmedia parameterを表現選択条件として照合する。
- `q`より後のaccept extensionを表現選択条件にしない。
- UTF-8 charset parameterを生成表現と照合する。
- 同一media typeでは、matching parameter数が多いrangeをよりspecificとして扱う。
- APIと非API routeで実装済みmethodだけを`Allow`に返す。
- helper testがWorkerの通常verifyに実際に含まれる。

## 期待する回帰条件

- `text/html;level=1;q=1, text/markdown;q=0.5`は、`level=1`を持たないHTMLではなくMarkdownを選ぶ。
- `text/html;charset=UTF-8;q=1, text/markdown;q=0.5`はHTMLを選ぶ。
- `text/html;q=0.8, text/html;charset=utf-8;q=0.4, text/markdown;q=0.6`は、よりspecificなHTML rangeの`q=0.4`を採用しMarkdownを選ぶ。
- `text/html;q=0;level=1, text/markdown;q=0.5`では`level=1`をaccept extensionとして扱いMarkdownを選ぶ。
- HTMLとMarkdownがともに`q=0`、または対応外media typeだけの場合は互換契約としてHTMLへfallbackする。
- API routeの`Allow`は`GET, HEAD, OPTIONS`、通常page routeは`GET, HEAD`とする。

## Hosted CI evidence

実装・回帰test・ADRを含むcommit `f6b0b18bb4df1a05c9490a92a1436d0dce99f612`をGitHub Actions CI run `32566260740`（run #250）で検証した。

- Cloudflare Worker on Node 22: success。
- Worker Vitest: `2 passed` test files、`46 passed` tests。内訳は`http.spec.ts` 15件、`worker.spec.ts` 31件。
- WebMCP Vitest: `1 passed` test file、`3 passed` tests。
- Worker type generation check、TypeScript typecheck、oxlintが成功。lintは0 warnings / 0 errors。
- Wrangler dry-run buildが成功。
- `npm audit --audit-level=high`: 0 vulnerabilities。
- Python 3.12 / 3.14のUbuntu、Windows、macOS、installed-wheel 3 OS、synthetic determinism 3 OSとcross-OS compareを含むCI全jobが成功。
- CI failure: 0。
- Worker test skip: 0。

この後のcommitは上記測定結果を固定する文書変更のみであり、Worker production codeと回帰testは変更しない。最終マージ前に、この文書変更を含むheadでも必須CIを再実行する。
