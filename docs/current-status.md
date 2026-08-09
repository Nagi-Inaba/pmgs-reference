# 現在の状態

- 更新日: 2026-08-09
- 実装状態: 公開出典表示の強化を実装済み
- 検証状態: repository全検査、Worker全検査、実データ全量A/B監査に合格
- 公開状態: 未デプロイ、外部URL未検証、外部検索index未検証

## 結論

ローカル正本、Python API、CLI、stdio MCP、公開export、Cloudflare Worker、OpenAPI、任意WebMCPは実装済みである。

公開HTML、Markdown、`llms.txt`は、帰属表示、JPOの原典案内URL、加工表示、非公式サービス表示を必須とするよう更新した。

公開JSONのsource objectは、owner、原典案内URL、帰属表示を必須とするよう更新した。

validatorは、いずれかの必須表示が欠けた候補を`notice_errors`付きで不合格にする。

この新しい公開契約は合成fixtureと実データ全量A/B監査で検証済みである。

現在のローカル状態は`full-data audited`である。

## 現在の公開契約

- v1のpublication policyは一つのsourceだけを受け付ける。
- 複数sourceを指定したpolicyはfail closedで拒否する。
- policyのattributionが正本SQLiteの`COPYRGHT`と一致しない場合は、出力directoryを作る前に拒否する。
- 公開分類recordはsource ID、相対識別子、owner、原典案内URL、SHA-256、attributionを持つ。
- HTMLとMarkdownは、日本語ページには日本語、英語ページには英語の加工表示と運営主体表示を持つ。
- トップページと`llms.txt`も同じ表示契約に従う。
- 元archive、正本SQLite、一括JSON、AI学習向けbulk提供は無効のまま維持する。

## 公式資料の確認

2026-08-09にJPO公式情報を再確認した。

[特許情報取得APIの公式案内](https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html)は第2.0版を現行手引き、第1.4版を改訂前手引きとして掲載している。

第2.0版PDFを`docs/evidence/`へ保存し、PDF signature、bytes、SHA-256を確認した。

第1.4版は履歴資料として保持し、現行資料とは表示しない。

JPOウェブサイトの利用案内は、出典の記載に加えて、編集または加工した場合の表示を求めている。

保存したPDFから生成するMarkdownは、機械的なテキスト抽出であることと原本PDF優先を表示する。

詳細は[登録条件と公開形態](registered-use-terms.md)と[公開証跡](evidence/README.md)に記録した。

## 現在差分の検査

2026-08-09時点でrepository標準検査に合格した。

- repository boundary: trackedまたはuntrackedの候補141件、違反0
- Ruff lint: 合格
- Ruff format: 63 file、差分0
- mypy: 21 source file、問題0
- pytest: 45件合格
- sdistとwheel: build成功、各27 file、禁止形式または非公開記載の検出0
- Worker: TypeScript、oxlint、workerd test 23件、WebMCP test 3件、dry-run bundleに合格
- npm audit: 脆弱性0
- Markdown: 34 file、相対link欠損0
- JSON: 11 file、parse error 0
- YAML: 7 file、parse error 0
- `git diff --check`: 合格

現行treeの公開前文言scanでは、秘密情報、実在端末path、認証情報、無関係なproject識別子を検出しなかった。

この検査は現在のfile内容を対象とする。

公開用`main`は、現在の公開候補だけを持つ単一root commitとして確定した。

旧履歴は外部backup bundleへ退避し、`main`から到達不能にした。

公開用履歴と現在treeのcredential pattern、禁止形式file、端末固有path、公開対象外の運用記録を検査した。

remoteは未設定で、pushは実施していない。

## 現在契約の全量監査

2026-08-09に新しい空の出力先へ実データA/B公開候補を生成した。

A/Bは各399,025 object、10,491,136,463 bytesだった。

tree SHA-256は`BB192477B7A99380476A1C161A00C2AED3FBBFB1ABC331908F93A751631C43D3`で一致した。

release manifest SHA-256は`18D24AC9524B9D7F8430B00EAAAE40A73B82FA744C52370BA90BCD562DB13A49`で一致した。

A/B各399,025ファイルのvalidatorは`valid=true`で、全error群と`notice_errors`は0件だった。

release auditは25条件すべて`true`、`ready=true`、`failures=[]`だった。

詳細は[2026-08-09の実データ公開候補検証](verification/public-release-2026-08-09.md)に記録した。

## 過去の全量検証

2026-08-08の旧表示契約では、実データA/B公開候補を各395,342 object、10,120,012,760 bytesで生成した。

旧候補のtree SHA-256は一致し、全件validatorとrelease auditは合格した。

この結果はparser、chunking、決定性、漏えい境界の回帰資料として保持する。

公開表示とsource schemaが変更されたため、旧候補のobject hashとtree hashは現在契約のリリースhashではない。

## 未完了の外部リリースゲート

1. GitHub-hosted CI、repository security設定、公開visibilityを外部で確認する。
2. 実originを確定したA/B再生成後に、R2 upload、Worker deploy、本番URL、sitemap、OpenAPIを外部で確認する。
3. 検索エンジンとAI検索からの発見性を公開後に測定する。

外部公開、package公開、deploy、index登録は、ローカル検証から自動的に完了扱いにしない。
