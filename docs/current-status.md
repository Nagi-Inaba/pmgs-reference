# 現在の状態

- 更新日: 2026-08-12
- 実装状態: 1コマンドでローカル環境を構築する`pmgs setup`をv0.3.0候補として実装済み。公開済みの`main`とGitHub Releaseはv0.2.0
- 検証状態: Windowsのローカル全検査、隔離wheel導入試験、JPPM2026002の独立A/B全量構築、v0.3.0 branchのGitHub hosted CI 10 jobに合格。追加hardening後のhosted CIとv0.3.0差分のCodeQLはPR前後の実行待ち
- 公開状態: GitHub source repositoryとv0.2.0 Releaseはpublic。v0.3.0、PyPI、R2、Worker、独自domain、外部検索indexは未公開

## 結論

v0.3.0候補では、取得済みPMGSパッケージを`pmgs setup`へ渡すだけで、棚卸し、SQLite構築、検証、実stdio MCP診断、現行版の切替までをWindows、macOS、Linuxで同じCLIから実行できる。

SQLiteはrelease、source manifest SHA-256、database SHA-256を含む内容アドレス付きpathへ保存する。検証済みの`state/current.json`だけを原子的に切り替え、旧版は保持する。同じsourceを再実行した場合はdatabaseとpointerを書き換えず再利用する。

CodexとClaude Codeを検出した場合は、MCP接続と共通skillを登録するか確認する。既に同じ設定があれば再利用し、内容の異なる同名設定やskillは上書きせず`conflict`として返す。Claude Codeの`CLAUDE_CONFIG_DIR`にも対応する。

data非同梱のwheelとsdistを作るrelease workflowも実装した。tagとpackage versionを照合し、source、Worker、隔離wheelを再検証した後、承認付き`pypi` environmentとTrusted PublishingでPyPIへ公開し、同じ成果物からGitHub Releaseを作る。workflowは未実行であり、v0.3.0を公開済みとは扱わない。

Web公開は停止したままである。第三者が費用と運用責任を引き受ける場合のR2・Worker手順と、GPTs、Gem、Copilot Studioの互換性境界は引き続き日英で提供する。

[GitHubのpublic repository](https://github.com/Nagi-Inaba/pmgs-reference)で現在公開されている安定版はv0.2.0である。R2への全量成果物upload、Worker deploy、PyPI公開、独自domain接続は行っていない。

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

## v0.3.0候補のローカル検査

2026-08-12にWindowsで現在の作業treeを検査した。

- `uv lock --check`: 合格
- repository boundary: trackedまたはuntrackedの候補168件、違反0
- Ruff lint: 合格
- Ruff format: 86 file、差分0
- mypy: 28 source file、問題0
- pytest: 106件合格、1件skip。skipはWindowsの現在の権限ではdirectory symlinkを作成できなかったためで、同じ試験をUbuntuとmacOSのhosted CIで実行する
- wheel導入試験: 空の隔離環境で初回setup=`ready`、再実行=`already_ready`、doctor=`true`、version=`pmgs 0.3.0`
- `pmgs_reference-0.3.0-py3-none-any.whl`: 98,306 bytes、SHA-256 `7ADD4CEE72574B5544D71ABE5DC345A7EF807CCFA32D0F3420923E4D12A60F05`
- `pmgs_reference-0.3.0.tar.gz`: 84,770 bytes、SHA-256 `EC4BADFA1A34237E641C4DCD2062FE375A8DF1BC6FC72121B7E07C2298FCBA0A`
- 配布内容: wheel 36 entry、sdist 37 entry、共通skill同梱、SQLite・source manifest・秘密鍵0件
- Worker: TypeScript、oxlint、workerd test 23件、WebMCP test 3件、dry-run bundleに合格
- npm audit: 脆弱性0
- PowerShell wrapper: parser error 0、`-WhatIf`でsetupを実行せず終了
- managed DB integrity: 通常queryはpathとmetadataを高速照合し、setupとdoctorは実ファイルSHA-256をpointerと照合する。DB改変時のsetup拒否、doctor失敗、診断中のcurrent pointer切替拒否を回帰testで確認
- client state: MCP登録後のskill失敗と、登録を見送った検出済みclientがある版切替でも`restart_required=true`を保持
- wheel再検証: `dist/`に0.1.0、0.2.0、0.3.0のwheelが共存する状態で、`pyproject.toml`の現行versionだけを選択して隔離導入試験に合格。version表示の期待値も同じproject versionから導出する
- `git diff --check`: 合格

配布物とrepositoryにはPMGS実データ、生成SQLite、全量export、登録情報、認証情報を含めていない。

## v0.3.0 branchのhosted CIとfresh clone

2026-08-12に`codex/pmgs-setup`をpublic repositoryへpushした。

[Hosted CI run 31506514581](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31506514581)はcommit `013a5b2209d941d9fb738f17d3a0ddcfea47a8e0`を検査し、次の10 jobがすべて成功した。

- Python 3.12と3.14 on Ubuntu、Windows、macOS: 6 job
- 隔離wheelからのsetup、再実行、doctor on Ubuntu、Windows、macOS: 3 job
- Cloudflare Worker on Node.js 22: 1 job

最初のrunではUnix runnerのmypyが`os.name`分岐を絞り込めず失敗した。lock実装の型分岐を`sys.platform`へ変更し、Windows、Linux、macOSを指定したmypyをローカルでも追加確認した。

次のrunでは既定DB探索のtestが`LOCALAPPDATA`だけを仮定してUnixで失敗した。OS非依存の既定data rootを注入するtestへ変更し、最終runで全OSが成功した。

同じpublic branchを新しいdirectoryへcloneし、remote SHA一致、署名済みPython 3.14からの新規仮想環境、repository boundary、Ruff、format、mypy、pytest 98件、隔離wheelのsetup、再実行、doctorを確認した。上記wheelとsdistのbytes、SHA-256、entry数はこのfresh cloneから作成した成果物である。

CodeQL default setupは有効だが、feature branchのpushには解析結果が作られず、default setupは手動dispatchにも対応しない。v0.3.0差分のCodeQLはPRまたはmainで確認する。

## v0.3.0 setupの実データ全量検証

2026-08-11にJPPM2026002を二つの独立した空のdata directoryへsetupした。

- source: 6,870 file、1,002,622,042 bytes、parsed 6,868、retained 2
- source manifest SHA-256: `96AA322D8D916406F4166FE1CFC9F6A1B749D09AFFB82EACD7B6557ECC215B52`
- A/B database: 各3,246,669,824 bytes
- A/B database SHA-256: `6C73443650E0CFF812D49EA24CF505F278B154471CC0C2A2C8FB2EBFB8743FD4`で一致
- setup: A/Bとも`ready`、validationと実stdio MCP診断に合格
- 再実行: `already_ready`。databaseと`current.json`のbytesおよび更新時刻は不変
- build issue: warning 41、error 0
- row count: concept 1,207,960、concept_property 1,428,529、concept_text 1,746,489、document 6,667、document_link 1,399,695、document_text 1,665,758、reference_entry 729、relation 1,863,942、source_file 6,870、source_record 4,430,638

このA/Bは同じv0.3.0候補による決定性を確認した。以前の異なるtoolchainで生成したdatabaseとのbyte一致は確認していないため、cross-toolchain determinismは未検証として残す。検証用databaseと実PMGS sourceはGitへ追加していない。

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

## v0.2.0のGitHub公開

[Pull Request #1](https://github.com/Nagi-Inaba/pmgs-reference/pull/1)は、必須checkをすべて通して2026-08-10にmergeした。merge commitは`cebd82caa76366c6d01e2fb9d27387b46dcfeb8f`である。

最初のCIではUbuntuだけが失敗した。仮想環境のPython symlinkをsystem interpreterへ解決したため、stdio子processが`pmgs_reference`をimportできなかったことが原因である。commit `650a3e3`で仮想環境のlauncher pathを保持し、再実行した。

[Hosted CI run 31363816163](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31363816163)では、Python 3.12と3.14をUbuntuとWindowsで検査し、Cloudflare WorkerをNode.js 22で検査した。5 jobすべてが成功した。

[CodeQL run 31363812624](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31363812624)では、Actions、Python、JavaScript/TypeScriptの3解析が成功した。

[GitHub Release v0.2.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.2.0)はdraftでもprereleaseでもなく、tagとtargetは上記merge commitを指す。添付した成果物は次のとおりである。

- `pmgs_reference-0.2.0-py3-none-any.whl`: 82,168 bytes、SHA-256 `F9122FCC21E378D35D3EFA99FAB61A0CFAC0CB803C62E5ABBC9F704974F68BCC`
- `pmgs_reference-0.2.0.tar.gz`: 71,233 bytes、SHA-256 `389EB97A9CBFD5A65AD9F56CB84360615E58E29C7975B3DEDAA930A48BA3F2E7`

GitHub asset digestはローカルSHA-256と一致した。wheelは32 file、sdistは33 fileで、共通skillを含み、PMGS実データ、SQLite、source manifest、全量export、禁止形式は0件だった。

repository descriptionは日本語である。R2 upload、Worker deploy、PyPI公開、独自domain接続は行っていない。

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

1. v0.3.0候補をPull Requestにし、CodeQLを確認する。mainのbranch protectionは旧5 checkのままなので、macOSと3 OS wheel checkを必須対象へ追加する。
2. GitHubには2026-08-12時点でenvironmentが0件であり、PyPIの`pmgs-reference` project endpointも404を返す。`pypi` environmentへrequired reviewerと`v*` tag制限を設定し、PyPI pending Trusted Publisherを登録する。404だけで将来の名前取得を保証しない。
3. v0.3.0 tagを作成し、承認後のPyPI project、attestation、GitHub Release、asset hash、空環境からの導入を外部確認する。
4. 第三者がWeb公開する場合だけ、現行契約で実originのA/Bを再生成し、R2 upload、Worker deploy、本番URL、sitemap、OpenAPIを確認する。
5. Web公開者が検索エンジンとAI検索からの発見性を測定する。

GitHub sourceとdata非同梱のv0.2.0 Releaseは公開済みである。v0.3.0、PyPI、全量成果物、Web deploy、index登録は完了扱いにしない。
