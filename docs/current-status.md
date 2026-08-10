# 現在の状態

- 更新日: 2026-08-10
- 実装状態: v0.2.0のCodex・Claude Code向けagent kit、日本語既定、英語切替、Webセルフホスト資料を実装済み
- 検証状態: 現行sourceはrepository全検査とWorker全検査に合格。日英Web入口追加後の実データ全量A/B監査とhosted CIは未実施
- 公開状態: GitHub source repositoryはpublic。v0.2.0のcommit、push、GitHub Releaseは未実施。R2、Worker、PyPI、独自domain、外部検索indexも未公開または未検証

## 結論

ローカル正本、Python API、CLI、stdio MCP、Codex・Claude Code用のclient別設定、共通skill、診断、評価ケースを実装した。

README、CLI help、skill、Web top、`llms.txt`は日本語を既定とし、英語版README、英語版ガイド、`language=en`、`/en/`、`llms.en.txt`を切替先にした。

Windows用setup scriptは、PMGS棚卸し、SQLite build、validation、実stdio診断、agent kit生成、skill導入を行う。既存DB、既存kit、内容の異なる同名skill、client設定は既定で上書きしない。

Web公開は停止したまま、第三者が費用と運用責任を引き受ける場合のR2・Worker手順と、GPTs、Gem、Copilot Studioの互換性境界を日英で公開する。

現行sourceと合成fixtureは`locally verified`である。2026-08-09に全量監査したSQLite正本と分類recordは回帰基準として有効だが、その後に追加した日英Web入口の公開bytesは実データ全量A/Bで再監査していない。

source repositoryの外部状態は`GitHub public`である。v0.2.0差分のcommit、push、GitHub Release、hosted CIは次の外部release gateである。

[GitHubのpublic repository](https://github.com/Nagi-Inaba/pmgs-reference)は通常のHTML閲覧とcloneが可能である。R2への全量成果物upload、Worker deploy、PyPI公開、独自domain接続は停止中の任意セルフホストgateであり、管理者は実施していない。

## 現在の公開契約

- v1のpublication policyは一つのsourceだけを受け付ける。
- 複数sourceを指定したpolicyはfail closedで拒否する。
- policyのattributionが正本SQLiteの`COPYRGHT`と一致しない場合は、出力directoryを作る前に拒否する。
- 公開分類recordはsource ID、相対識別子、owner、原典案内URL、SHA-256、attributionを持つ。
- HTMLとMarkdownは、日本語ページには日本語、英語ページには英語の加工表示と運営主体表示を持つ。
- `/`と`/ja/`の日本語top、日本語`llms.txt`、`/en/`の英語top、`llms.en.txt`が同じ表示契約に従う。
- API、CLI、skillの既定言語は日本語であり、英語を明示的に選択できる。
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

2026-08-10時点で現行sourceのrepository標準検査に合格した。

- repository boundary: trackedまたはuntrackedの候補155件、違反0
- Ruff lint: 合格
- Ruff format: 74 file、差分0
- mypy: 24 source file、問題0
- pytest: 56件合格
- agent kit focus: 8件合格。実stdio、hash不変、TOML、JSON、skill冪等、途中失敗回収、日本語既定を確認
- sdistとwheel: v0.2.0 build成功。sdist 33 file、wheel 32 file、skill resource同梱、禁止形式0
- Worker: TypeScript、oxlint、workerd test 23件、WebMCP test 3件、dry-run bundleに合格
- npm audit: 脆弱性0
- Markdown: 42 file、相対link 57件、欠損0
- JSON: 12 file、parse error 0
- YAML: 8 file、parse error 0
- 配布skill validator: 合格
- PowerShell setup: parser error 0、`-WhatIf`で外部変更なしの到達確認に合格
- `git diff --check`: 合格

現行treeの公開前文言scanでは、秘密情報、実在端末path、認証情報、無関係なproject識別子を検出しなかった。

この検査は現在のfile内容を対象とする。

公開用`main`は、現在の公開候補だけを持つclean root commit `c3f836b`から開始した。

その後の`077ccc3`はWindows Python 3.12でCSV field size上限がoverflowする問題だけを修正し、同条件の回帰testを追加した。

旧履歴は外部backup bundleへ退避し、`main`から到達不能にした。

公開用履歴と現在treeのcredential pattern、禁止形式file、端末固有path、公開対象外の運用記録を検査した。

`origin`は`https://github.com/Nagi-Inaba/pmgs-reference.git`で、`main`をpush済みである。

## GitHub source repositoryの公開検証

2026-08-09に`Nagi-Inaba/pmgs-reference`をpublic repositoryとして外部確認した。

- public URL: [https://github.com/Nagi-Inaba/pmgs-reference](https://github.com/Nagi-Inaba/pmgs-reference)
- default branch: `main`
- license表示: Apache-2.0
- Issues: enabled
- Wiki、Projects、Discussions: disabled
- Actionsの既定permission: read-only、pull request承認permission: disabled
- Dependabot alertsとsecurity updates: enabled
- secret scanningとpush protection: enabled
- private vulnerability reporting: enabled
- branch protection: 実在する5 hosted checkを必須化、force pushとbranch deletionを禁止

[Hosted CI run 31305434936](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31305434936)では、Python 3.12と3.14をUbuntuとWindowsで検査し、Cloudflare WorkerをNode.js 22で検査した。5 jobすべてが成功した。

最初の非公開runではWindows Python 3.12だけがCSV 19件を失敗扱いにした。原因は`csv.field_size_limit(sys.maxsize)`が同環境のsigned C long上限を超えることだった。portable上限を`2^31-1`へ固定し、回帰testを追加した後のrun 31305434936で同環境を含む全jobが成功した。

[CodeQL setup run 31305563795](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31305563795)はActions、Python、JavaScript/TypeScriptの解析に成功した。default setupはweekly scheduleである。

## 2026-08-09の直前契約に対する全量監査

2026-08-09に新しい空の出力先へ実データA/B公開候補を生成した。

A/Bは各399,025 object、10,491,136,463 bytesだった。

tree SHA-256は`BB192477B7A99380476A1C161A00C2AED3FBBFB1ABC331908F93A751631C43D3`で一致した。

release manifest SHA-256は`18D24AC9524B9D7F8430B00EAAAE40A73B82FA744C52370BA90BCD562DB13A49`で一致した。

A/B各399,025ファイルのvalidatorは`valid=true`で、全error群と`notice_errors`は0件だった。

release auditは25条件すべて`true`、`ready=true`、`failures=[]`だった。

詳細は[2026-08-09の実データ公開候補検証](verification/public-release-2026-08-09.md)に記録した。

この監査後に`index.en.html`と`llms.en.txt`を追加し、日本語`llms.txt`を既定にした。したがって、上記tree hashとobject countは現行Web入口契約のrelease hashではない。第三者がWeb公開する場合は、実originでA/Bを新規生成して再監査する。

## 過去の全量検証

2026-08-08の旧表示契約では、実データA/B公開候補を各395,342 object、10,120,012,760 bytesで生成した。

旧候補のtree SHA-256は一致し、全件validatorとrelease auditは合格した。

この結果はparser、chunking、決定性、漏えい境界の回帰資料として保持する。

公開表示とsource schemaが変更されたため、旧候補のobject hashとtree hashは現在契約のリリースhashではない。

## 未完了の外部リリースゲート

1. v0.2.0差分をcommitしてpublic GitHub repositoryへpushし、hosted CIを確認する。
2. GitHub Releaseへdataを含まないsdistとwheelを添付し、公開状態を確認する。
3. 第三者がWeb公開する場合だけ、実originでA/Bを再生成し、R2 upload、Worker deploy、本番URL、sitemap、OpenAPIを外部確認する。
4. Web公開者が検索エンジンとAI検索からの発見性を測定する。

GitHub以外の全量成果物公開、package公開、deploy、index登録は、ローカル検証から自動的に完了扱いにしない。
