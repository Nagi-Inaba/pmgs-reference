# 現在の状態

- 更新日: 2026-08-14
- 実装状態: v0.4.0の分類revision、出典、validation、AI参照契約、PMGS保有者向け導線をPull Request #6と#8からmainへ統合済み
- 検証状態: **source統合済み**。Claude Codeのlive MCP評価だけは、現在利用できる無料アカウントでは評価に必要なClaudeモデル呼出しを実行できないため`not_observed`
- 公開状態: GitHub source repository、[PyPI v0.4.0](https://pypi.org/project/pmgs-reference/0.4.0/)、[GitHub Release v0.4.0](https://github.com/Nagi-Inaba/pmgs-reference/releases/tag/v0.4.0)は公開済み。R2、Worker、独自domain、外部検索indexは未公開のままHold

PMGS保有者向けの導線は、日英READMEと導入ガイドでinstall、展開済みdirectory、書き込みなしdry-run、容量確認、setup、doctor、lookupの順へ統一した。AI向けには同じ手順を機械可読YAMLで示し、原archive・展開後の原資料・SQLite・一括exportをアップロードせず、ローカルMCPの上限付き結果だけを証拠として使う境界をskillとMCP tool descriptionにも追加した。

2026年8月14日に、別のPMGS releaseを使う手順を日英READMEと導入ガイドへ追加した。実際の`JPPM`版directoryを直接指定する方法、任意名directoryだけで`--release`を使う方法、名前だけでは版を確認できない境界、複数版の安全な切替、未知形式のfail-closed、固定v0.4.0導入、独自`--data-dir`でのlookup、Codex・Claude Code CLIの前提、macOS・Linuxの一行例を同じオンボーディング契約として記録した。

ユーザーは2026年8月13日にv0.4.0のPyPI公開、tag、GitHub Releaseを承認した。[Release run 31677401736](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31677401736)は、required reviewer付き`pypi`環境、`v*` tag制限、Trusted Publishing、digital attestationを通過し、同じwheelとsdistをPyPIとGitHub Releaseへ公開した。両配布面のSHA-256、PyPI provenance、空環境からの`uv tool install`、setup、doctor、lookup、MCP tool 3件を外部確認した。

## 結論

v0.4.0は監査で確認したIPC版混在、FI改正関係の欠落、出典固定値、validationとAI参照契約の不足を修正し、ローカル検証、実データA/B監査、Codex実MCP評価、hosted CI、CodeQLに合格した。sourceはmainへ統合済みである。
Claude Code用のMCP設定、共通skill、登録、分離環境、tool制限は回帰testで検証した。live MCP評価は、現在利用できる無料アカウントでは評価に必要なClaudeモデル呼出しを実行できないため`not_observed`であり、成功済みとは扱わない。ユーザーは2026年8月13日に、この未観測を残余リスクとして記録したうえでsourceをmainへ統合することを承認し、同日にv0.4.0のtag、PyPI、GitHub ReleaseのHoldも解除した。R2、Worker、独自domain、外部検索indexのHoldは維持する。

2026年8月13日の最終候補A/Bは、JPPM2026002のsource 6,870件とsource record 4,430,638件を
NTFSとexFATの独立した空の出力先へそれぞれschema v2で再構築した。
両候補はdatabase、build report、validation reportのbytesとSHA-256が一致し、
同じlogical digestになった。両候補とも54件のvalidation、7件のdoctor検査すべてに合格した。
Codexは隔離wheelを使った実MCP評価の全ケースに合格し、禁止tool呼出しは0件だった。
公開exportのA/Bも454,303 object、14,406,835,616 bytes、tree SHA-256まで一致し、
全件validationと25条件のrelease auditに合格した。
その後追加したlink・reparse・読込時identity検査とHTML/CSS拒否条件を含む最終validatorで、
A/B各454,303 objectを再検証した。両方とも`valid=true`、全error群0で、tree SHA-256と
validation report SHA-256が一致した。25条件のrelease auditも`ready=true`、failure 0で合格した。
独立code reviewとsecurity reviewの未解決Critical、High、Mediumは0件である。
commit `4ec6738`は、GitHub ActionsのPython 6 job、3 OS wheel、3 OS合成決定性、
決定性比較、Workerからなる14 jobすべてに合格した。CodeQLもActions、Python、
JavaScript/TypeScriptの3解析すべてに合格した。
[Push CI run 31634401819](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634401819)、
[Pull Request CI run 31634407211](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634407211)、
[CodeQL run 31634403653](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31634403653)はすべて成功した。
2026年8月12日のClaude Code評価は認証エラーで終了した。その後、custom設定rootを保持する修正と回帰testを追加したが、現在利用できる無料アカウントでは評価に必要なClaudeモデル呼出しを実行できず、修正後のlive MCP互換性は`not_observed`である。

[Pull Request #6](https://github.com/Nagi-Inaba/pmgs-reference/pull/6)は2026年8月13日にsquash mergeされ、
mainの実装commitは`19ab5e11c256c2fba6db4ffa1f1cfe3e5e79eeac`になった。
[Main CI run 31662197654](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31662197654)は
14 jobすべてに成功し、[Main CodeQL run 31662197622](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31662197622)も
Actions、Python、JavaScript/TypeScriptの3解析すべてに成功した。

[Pull Request #8](https://github.com/Nagi-Inaba/pmgs-reference/pull/8)はPMGS保有者向け導線とAI向け説明をmain commit
`5550ad6f93f85b818258f634bed89d1a407b35a5`へsquash mergeした。
[Main CI run 31677175162](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31677175162)の14 jobと
[Main CodeQL run 31677174521](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31677174521)の3解析はすべて成功した。

測定値、未観測事項、外部公開Holdは
[v0.4.0の正確性検証](verification/v0.4-correctness-2026-08-12.md)へ記録する。

以下のv0.3.0記録は、旧契約の回帰基準と外部公開状態を示すものであり、v0.4.0の完成を意味しない。

v0.3.0候補では、取得済みPMGSパッケージを`pmgs setup`へ渡すだけで、棚卸し、SQLite構築、検証、実stdio MCP診断、現行版の切替までをWindows、macOS、Linuxで同じCLIから実行できる。

SQLiteはrelease、source manifest SHA-256、database SHA-256を含む内容アドレス付きpathへ保存する。検証済みの`state/current.json`だけを原子的に切り替え、旧版は保持する。同じsourceを再実行した場合はdatabaseとpointerを書き換えず再利用する。

CodexとClaude Codeを検出した場合は、MCP接続と共通skillを登録するか確認する。既に同じ設定があれば再利用し、内容の異なる同名設定やskillは上書きせず`conflict`として返す。Claude Codeの`CLAUDE_CONFIG_DIR`にも対応する。

data非同梱のwheelとsdistを作るrelease workflowも実装した。tagとpackage versionを照合し、source、Worker、隔離wheelを再検証した後、承認付き`pypi` environmentとTrusted PublishingでPyPIへ公開し、同じ成果物からGitHub Releaseを作る。v0.3.0候補ではworkflowを実行せず、公開済みとは扱わなかった。

Web公開は停止したままである。第三者が費用と運用責任を引き受ける場合のR2・Worker手順と、GPTs、Gem、Copilot Studioの互換性境界は引き続き日英で提供する。

[GitHubのpublic repository](https://github.com/Nagi-Inaba/pmgs-reference)の`main`をsourceの配布面とする。
Python packageの最新版はPyPIとGitHub Releaseで公開したv0.4.0である。R2への全量成果物upload、Worker deploy、独自domain接続は行っていない。

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
- pytest: 110件合格、1件skip。skipはWindowsの現在の権限ではdirectory symlinkを作成できなかったためで、同じ試験をUbuntuとmacOSのhosted CIで実行する
- wheel導入試験: 空の隔離環境で初回setup=`ready`、再実行=`already_ready`、doctor=`true`、version=`pmgs 0.3.0`
- `pmgs_reference-0.3.0-py3-none-any.whl`: 98,788 bytes、SHA-256 `A852C1E9D478BD2F595FEA2BF6FBD4997A48A83DF6671A65E05507C409EABC42`
- `pmgs_reference-0.3.0.tar.gz`: 85,319 bytes、SHA-256 `7C3D22C7F4102FE00AF9FF20BAC786773C04D477B54AAC593AAD54213746CF73`
- 配布内容: wheel 36 entry、sdist 37 entry、共通skill同梱、SQLite、source manifest、秘密鍵は0件
- Worker: TypeScript、oxlint、workerd test 23件、WebMCP test 3件、dry-run bundleに合格
- npm audit: 脆弱性0
- PowerShell wrapper: parser error 0、`-WhatIf`でsetupを実行せず終了
- managed DB integrity: 通常queryはpathとmetadataを高速照合し、setupとdoctorは実ファイルSHA-256をpointerと照合する。DB改変時のsetup拒否、doctor失敗、診断中のcurrent pointer切替拒否を回帰testで確認
- client state: MCP登録後のskill失敗と、登録を見送った検出済みclientがある版切替でも`restart_required=true`を保持
- wheel再検証: `dist/`に0.1.0、0.2.0、0.3.0のwheelが共存する状態で、`pyproject.toml`の現行versionだけを選択して隔離導入試験に合格。version表示の期待値も同じproject versionから導出する
- setup状態: 保存済みDBを使ってrelease AからBへ切り替え、再びAへ戻した場合は`already_ready`ではなく`ready`を返す。
  旧`current.sqlite`へpointerを追加するだけの場合は`already_ready`を維持する
- DB配置: ハードリンク非対応時の排他的配置、配置失敗時の一時ファイル回収、同時に作成された出力先の非上書きを回帰testで確認
- `git diff --check`: 合格

配布物とrepositoryにはPMGS実データ、生成SQLite、全量export、登録情報、認証情報を含めていない。

## v0.3.0のGitHub Actions検証、レビュー、main統合

2026-08-12に`codex/pmgs-setup`をpublic repositoryへpushした。

[Hosted CI run 31506514581](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31506514581)はcommit `013a5b2209d941d9fb738f17d3a0ddcfea47a8e0`を検査し、次の10 jobがすべて成功した。

- Python 3.12と3.14 on Ubuntu、Windows、macOS: 6 job
- 隔離wheelからのsetup、再実行、doctor on Ubuntu、Windows、macOS: 3 job
- Cloudflare Worker on Node.js 22: 1 job

最初のrunではUnix runnerのmypyが`os.name`分岐を絞り込めず失敗した。lock実装の型分岐を`sys.platform`へ変更し、Windows、Linux、macOSを指定したmypyをローカルでも追加確認した。

次のrunでは既定DB探索のtestが`LOCALAPPDATA`だけを仮定してUnixで失敗した。OS非依存の既定data rootを注入するtestへ変更し、最終runで全OSが成功した。

同じpublic branchを新しいdirectoryへcloneし、remote SHA一致、署名済みPython 3.14からの新規仮想環境、repository boundary、Ruff、format、mypy、pytest 98件、隔離wheelのsetup、再実行、doctorを確認した。
このfresh cloneはcommit `013a5b2209d941d9fb738f17d3a0ddcfea47a8e0`を対象とし、source checkoutに依存しない導入経路を確認した。
最終commitの配布物は、上記のローカル検査で2回構築し、bytesとSHA-256の一致を確認した。

[Pull Request #4](https://github.com/Nagi-Inaba/pmgs-reference/pull/4)では、最終commit `efccc3ff8aca68e1c6b4ad0d7e0ca5c1ae844968`に対して、branchへのpush時とPull Request更新時の両方でCIを実行した。
[Push CI run 31512828783](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31512828783)と[Pull Request CI run 31512833620](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31512833620)は、いずれも10 jobすべてが成功した。

[CodeQL run 31512829489](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31512829489)はActions、Python、JavaScript/TypeScriptの3解析に成功し、未解決アラートは0件だった。
初回の自動レビューによる2件の指摘を回帰test付きで修正し、[最終レビュー](https://github.com/Nagi-Inaba/pmgs-reference/pull/4#issuecomment-5256060409)は最終commitに重大な問題を検出しなかった。

Pull Request #4は2026-08-12にsquash mergeされ、`main`はcommit `95a1d3eec7e9bfd805ea313ffe3b61974241d9ad`になった。
[Main CI run 31513770595](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31513770595)は10 jobすべてに成功した。
[Main CodeQL run 31513778284](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/31513778284)も3解析すべてに成功した。

`main`のbranch protectionとrulesetは、Python 6 job、3 OSのwheel 3 job、Worker 1 jobからなる同じ10件のcheckをstrictで必須化している。
force pushとbranchの削除を禁止している。2026年8月13日の再確認では、Pull Request review、
レビュー会話の解決、linear historyはrepository ruleとして必須化されていない。v0.4.0では
Pull Requestと独立reviewを手動の統合ゲートとして扱う。

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
- branch protectionとruleset: 実在する10件のhosted checkをstrictで必須化し、force pushとbranchの削除を禁止

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

v0.2.0公開時点のrepository descriptionは日本語であった。R2 upload、Worker deploy、PyPI公開、独自domain接続は行っていなかった。

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

## 完了したPythonリリースと残るWebゲート

1. GitHubの`pypi` environmentはrequired reviewerと`v*` tag制限を適用し、`v0.4.0`のdeploymentを承認した。PyPI Trusted Publisherは`Nagi-Inaba/pmgs-reference`、`release.yml`、`pypi`の組合せで公開に成功した。
2. PyPI project、両fileのprovenance、GitHub Release、asset hash、空環境からの導入を外部確認した。公開fileのhashと導入結果は[v0.4.0の正確性検証](verification/v0.4-correctness-2026-08-12.md#v040-pythonパッケージの外部公開)へ記録した。
3. 第三者がWeb公開する場合だけ、現行契約で実originのA/Bを再生成し、R2 upload、Worker deploy、本番URL、sitemap、OpenAPIを確認する。
4. Web公開者が検索エンジンとAI検索からの発見性を測定する。

GitHub repositoryの`main`にあるソースコードと、data非同梱のv0.4.0 wheel・sdistは公開済みである。
全量成果物、Web deploy、独自domain、index登録は完了扱いにしない。
