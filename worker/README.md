# PMGS Reference Worker

Cloudflare Worker と R2 で、Python が事前生成した PMGS Reference の公開成果物を読み取り専用で配信する。

Worker は PMGS 原資料を解析しない。分類照会は group manifest と対象 JSON chunk の最大2回、文書照会も document manifest と対象 JSON chunk の最大2回の R2 読み取りで完了する。HTML、Markdown、manifest などの直接配信は R2 body をストリーミングする。

## 公開ルート

- `GET /api/v1/lookup`：FI、Fターム、IPC の完全一致照会
- `GET /api/v1/documents/{document_id}`：JPO提供文書のページまたは節
- `GET /api/v1/releases`、`GET /api/v1/coverage`：公開版と coverage
- `/ja/...`、`/en/...`：HTML。`Accept: text/markdown` では同内容の Markdown
- `/releases/{release}/...`：不変の版付き JSON と manifest
- `/openapi.json`、`/llms.txt`、`/robots.txt`、`/sitemap.xml`
- `/assets/webmcp.js`：対応ブラウザだけが利用する任意の WebMCP 登録スクリプト

## 版の切替

`wrangler.jsonc` の `RELEASE_CATALOG_JSON` が公開可能な版の allowlist、`CURRENT_RELEASE` が `current` の実体である。R2 上の可変ファイルから現在版を自動判定しない。

新しい版は、先に全成果物を R2 へ追加して hash を検証し、その後に catalog と current を変更する。旧版オブジェクトは切替時に削除しない。

## ローカル検証

Node.js 22 と `package-lock.json` を使用する。

```powershell
npm ci
npm run verify
```

`npm run verify` は次を順に検証する。

1. Wrangler 生成型が `wrangler.jsonc` と一致すること
2. Worker と WebMCP の TypeScript 型検査
3. floating promise を含む静的解析
4. workerd 上の R2・route 統合テストと WebMCP の feature detection テスト
5. WebMCP bundle と Worker dry-run bundle
6. high 以上を含む npm 依存脆弱性がないこと

`compatibility_date` は、使用中の Wrangler が同梱する workerd の対応範囲内で最も新しく検証した日へ固定する。日付だけを当日に進めず、`npm run verify` が通る組合せで更新する。

チャンク上限を見直す場合は、通常ゲートと分けて次を実行する。

```powershell
npm run benchmark:chunks
```

出力はローカルworkerd、ローカルR2 simulatorを含むend-to-end wall-clockであり、本番WorkersのCPU課金時間ではない。上限決定の比較資料に使い、本番CPUはdeploy後に観測する。

## 外部操作の境界

このディレクトリの通常検証は `wrangler deploy --dry-run` までである。R2 upload、実 deploy、custom domain、DNS、Git push は行わない。
