# 公開API契約

[English](public-api.en.md)

## 分類照会

```http
GET /api/v1/lookup?scheme=fi&code=G06F3%2F048&release=current&language=ja
```

`scheme`と`code`は必須である。

`scheme`は`fi`、`fterm`、`ipc`のallowlistから選ぶ。

`language`は`ja`または`en`とし、省略時は`ja`とする。

`version`はIPCだけで指定でき、`YYYY.MM`形式とする。FIまたはFタームで指定した場合は
`INVALID_VERSION`を返す。`relation_limit`は既定50、最大200、`relation_offset`は既定0である。

同じcodeの全revisionは一つのstorage bundleに入り、Workerは有効期間を計算せず、事前生成済みの
基準日recordまたは指定versionの`revision_records`を選ぶ。指定versionが存在しない場合と、基準日に
有効なrevisionがない場合もHTTP 200で、それぞれ`version_not_found`、`not_valid_at_release`を返す。

## 文書照会

```http
GET /api/v1/documents/{document_id}?release=current&page=1
```

`document_id`はexport manifestに存在する識別子だけを受け付ける。

`page`または`section`は任意であり、同時指定は許可しない。

`release`は省略時に`current`となる。公開可能な版だけをWorkerのrelease catalogへ登録する。

## HTTP状態

| 状態 | HTTP | code |
|---|---:|---|
| 正常 | 200 | なし |
| scheme不正 | 400 | `INVALID_SCHEME` |
| code不正 | 400 | `INVALID_CODE` |
| language不正 | 400 | `INVALID_LANGUAGE` |
| FI・Fタームのversion指定またはversion形式不正 | 400 | `INVALID_VERSION` |
| 指定したIPC versionが存在しない | 200 | `match_status=version_not_found` |
| 基準日の有効版なし | 200 | `match_status=not_valid_at_release` |
| release不明 | 404 | `RELEASE_NOT_FOUND` |
| 分類なし | 404 | `CLASSIFICATION_NOT_FOUND` |
| 文書なし | 404 | `DOCUMENT_NOT_FOUND` |
| 成果物不整合 | 503 | `RELEASE_UNAVAILABLE` |

APIは`Access-Control-Allow-Origin: *`を返す。

全応答は`Content-Signal: search=yes, ai-input=yes, ai-train=no`とsecurity headerを返す。

版付き応答は長期cache、`current`応答は短期cacheとする。

正常な分類照会と文書照会は、manifestと対象chunkの最大2回のR2読み取りで完了する。成果物不整合や8 MiBを超えるJSON objectは推測で返さず503とする。

## 安全境界

利用者入力をR2 keyへ直接連結しない。

Workerは検証済みmanifestと固定prefixからR2 keyを解決する。

エラー応答はローカルパス、内部key、stack traceを返さない。

## 公開成果物契約

`pmgs export-public`は`base_url`を必須入力とし、次を生成する。

- `/releases/{release}/groups/.../manifest.json`：lookup key範囲とJSONチャンクのhash
- `/releases/{release}/groups/.../{chunk}.json`：日英の公式値を保持する保存レコード
- `/releases/{release}/site/{language}/.../{chunk}.html`：JavaScript不要の閲覧ページ
- `/releases/{release}/site/{language}/.../{chunk}.md`：AIが取得しやすい同内容のMarkdown
- `/releases/{release}/documents/{document_id}/...`：公式文書のmanifestと節チャンク
- `/releases/{release}/manifest.json`：全公開オブジェクトのbytes、SHA-256、content type

保存レコードは日英を一緒に持つ。

分類record 2.0は`reference_date`、`record_status`、選択された`version`と有効期間、
`available_versions`を持つ。関係は`relation_count`、`relation_offset`、`relation_limit`、
`relations_truncated`、`next_relation_offset`を伴う安定したpageとして返す。

同一codeのbundleはJSON chunkをまたがない。単一bundleが固定上限256 KiBを超える場合、
exportは成功扱いにせず拒否する。

WorkerはAPI応答時に指定言語の出典由来値だけを`classification-record.schema.json`へ射影する。

各source objectは`source_id`、`title`、`relative_id`、`owner`、`original_url`、`sha256`、`attribution`を必須とする。

`original_url`はJPOの原典案内ページを指し、PMGS package内の個別file download URLを推測しない。

チャンク`001`の公開URLは番号を省略し、`002`以降は末尾へ番号を付ける。分類fragmentは必ず実際にその分類を含むページへ向ける。

`index.html`と`llms.txt`は日本語正本、`index.en.html`と`llms.en.txt`は英語切替先として生成する。Workerは`/`と`/ja/`で日本語top、`/en/`で英語topを返す。

`openapi.json`、`robots.txt`、`sitemap.xml`も同じビルドで生成する。公開成果物にCSV、XML原資料、PDF、SQLite、一括JSONは含めない。

## HTMLとWebMCP

分類ページは通常のHTMLとしてJavaScriptなしでも読める。

`Accept: text/markdown`を指定すると、同じ版と出典を持つ事前生成Markdownを返す。

HTML、Markdown、日英トップページ、日英`llms.txt`はattribution、JPOの原典案内URL、加工表示、非公式サービス表示を含む。

validatorはこれらの表示が欠けた候補を`notice_errors`で不合格にする。

全HTMLは`/assets/webmcp.js`を任意追加層として読み込む。対応ブラウザで`document.modelContext`が存在する場合だけ、読み取り専用の`lookup_patent_classification`を1件登録する。toolは同一オリジンの分類APIを呼び、別の定義やAI要約を生成しない。

GPTsとGemのWeb参照はHTML、Markdown、sitemapを入口にするが、indexや特定domainの利用は保証されない。

`openapi.json`はOpenAPI 3.1対応clientの入口である。GPT ActionsまたはCopilot Studioが異なるOpenAPI版を要求する場合は、同じHTTP契約から互換定義を生成して別途検証する。
