# ADR 0004：Worker の版解決と WebMCP を公開データから分離する

- 状態：採用
- 日付：2026-08-08
- 一部置換：外部AI clientの互換性判断は[ADR 0007](0007-local-agent-kit-and-optional-web-hosting.md)を優先する

## 文脈

公開 API は、FI、Fターム、IPC の体系と版を混同せず、破損した成果物を推測で補わず、Cloudflare Workers Free の CPU と R2 読み取りを小さく保つ必要がある。

WebMCP は対応ブラウザがまだ限定される提案段階の入口であり、GPTs、Gem、Copilot Studio の共通入口にはできない。

## 決定

公開可能な release は Worker 環境変数 `RELEASE_CATALOG_JSON` の allowlist へ明示する。`CURRENT_RELEASE` は `release=current` の解決先とし、R2 の一覧や可変 pointer から暗黙に切り替えない。

分類 API は、正規化済み lookup key の範囲を group manifest で二分探索し、該当 JSON chunk だけを読む。文書 API は document manifest の page または sequence index から該当 chunk だけを読む。いずれも正常応答は最大2回の R2 読み取りとする。

保存 JSON は最大8 MiBまでしか Worker メモリへ展開しない。HTML、Markdown、CSS、manifest の直接配信は R2 body をストリーミングし、リクエスト中に PMGS 形式の解釈や HTML 生成を行わない。

`webmcp.js` は Workers Static Assets から同一オリジン配信する。`document.modelContext.registerTool()` が存在する場合だけ、読み取り専用の `lookup_patent_classification` を1件登録する。tool は同じ `/api/v1/lookup` を呼び、別の分類ロジックを持たない。登録不能でも通常の HTML、Markdown、JSON API は変化しない。

## 結果

- current の切替は Worker deploy という明示操作になり、R2 upload 途中の版を誤配信しない。
- 分類と文書の正常照会は最大2回の R2 読み取りで試験できる。
- GPT Actions、Gem、Copilot Studio は OpenAPI と通常 HTTP を使え、WebMCP 対応有無に依存しない。
- WebMCP 仕様変更時は `worker/webmcp/` と静的 bundle だけを交換できる。
- release catalog更新と実deployは、ローカル公開候補の完成とは別の外部release工程に残る。
