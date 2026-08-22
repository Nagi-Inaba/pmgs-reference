# Doctor runtime and complete-tool verification — 2026-08-22

対象PR: #41  
対象Issue: #15、#16

## 目的

`pmgs doctor`と`pmgs setup`のstdio MCP診断を有界時間で終了させ、公開している3 toolを実際に呼び出してからDBを利用可能と判定する。

## 検証対象

- `--timeout-seconds`と`doctor_database(timeout_seconds=...)`は有限の正数だけを受け付ける。
- 起動、初期化、tool列挙、各tool呼び出し、終了処理を一つのcancel boundaryで有界化する。
- timeout時は`MCP_TIMEOUT`とactive stageを返し、stdio子プロセスを終了・回収する。
- timeout後に同じ`data_dir`で`pmgs setup`を再実行できる。
- `lookup_classification`、`search_pmgs`、`get_pmgs_document`を実stdio経由で個別に呼び出す。
- tool名、read-only annotation、各structured response、source、件数、照会前後SHA-256を検査する。
- 決定的sampleを選択できない場合は`SAMPLE_SELECTION_FAILED`、tool応答の構造契約に失敗した場合は`MCP_CONTRACT_FAILED`を返す。
- reportにはローカル絶対path、sample query本文、取得本文、excerpt、source pathを含めない。
- 日本語・英語のローカル参照文書を同じ契約へ同期する。

## 回帰テスト

- `tests/test_doctor_contract.py`
  - timeout cancel時のasync context解放
  - stage別timeout
  - 実在する停止stdio子プロセスのPID確認と終了確認
  - Windows、macOS、Linuxでの同一cleanup contract
  - 0、負数、NaN、infinityの拒否
  - timeout、sample選択失敗、tool contract失敗の構造化結果
  - 3 toolの実呼び出し
  - search handlerまたはdocument handlerだけが故障した場合の失敗
  - reportから本文と絶対pathが除外されること
- `tests/test_doctor_setup_contract.py`
  - doctor timeout後にsetup lockが解放され、同じ`data_dir`で再実行できること
- `tests/fixtures/hanging_stdio_server.py`
  - PIDを記録して無期限停止するcross-platform test child

## 失敗と修正履歴

### CI run 32569514808（run #289）

- Ubuntuのpytestは`17 failed, 248 passed, 5 skipped, 1 error`だった。
- 文書toolの実応答が`source`単数であるのにdoctorが`sources`複数を検査しており、`sample_document`失敗からsetup系へ連鎖した。
- `tests/test_doctor_setup_contract.py`のmodule alias `setup_module`がpytestのxUnit hook名と衝突した。
- doctorのdocument contractを`source.relative_id`へ修正し、aliasを`setup_service`へ変更した。

### CI run 32569723904（run #295）

- 上記修正後、Ubuntu Python 3.12で`266 passed, 5 skipped`、repository boundary、Ruff、mypy、buildが成功した。
- その後、Issue #16の「本文全量やローカル絶対pathをreportへ出さない」条件を再確認し、reportをstatus/count/hashの要約へ縮小した。

## Hosted CI evidence

commit `d960efb7019f3804594efd2308df8a48f91d7a0f`をGitHub Actions CI run `32569948645`（run #299）で検証し、全jobが成功した。

### Ubuntu Python 3.12

- repository boundary: 189 candidate files、違反なし
- Ruff check: success
- Ruff format check: `105 files already formatted`
- mypy: `Success: no issues found in 29 source files`
- pytest: `266 passed, 5 skipped in 31.50s`
- wheel / sdist build: success

skip 5件はWindows固有の既存契約であり、本変更固有のfailureまたはskipは0件だった。

### Windows Python 3.12

- repository boundary: 189 candidate files、違反なし
- Ruff、format、mypy: success
- pytest: `271 passed in 63.50s`
- wheel / sdist build: success

Windowsでは実子プロセスcleanup試験を含む全testがskipなしで成功した。

### Full matrix

次を含むrun #299の全jobが成功した。

- Python 3.12 / 3.14 on Ubuntu、Windows、macOS
- Python 3.13 on Ubuntu
- installed wheel on Ubuntu、Windows、macOS
- installed wheel on Python 3.13
- Cloudflare Worker on Node 22
- synthetic determinism on Ubuntu、Windows、macOSとcross-OS compare

## Report boundary

`DoctorResult.as_dict()`はDBのファイル名だけを返す。sample queryはSHA-256、各toolの結果はschema version、status、件数、source有無などの要約だけを返す。取得本文、excerpt、検索語本文、ローカル絶対path、source pathはreportへ保存しない。

## 未観測項目

- 本変更のhosted CIは追跡済み合成fixtureを使用した。
- 実PMGSに対する3 tool doctorは、この変更のCIでは再観測していない。
- 実PMGSの評価を行う場合も、元資料、SQLite、絶対path、本文全量を公開repositoryや外部AIへ送らない。

## 最終判定

検証記録と日英文書を追加した最新headに対してrequired CIを再実行し、その全成功を最終マージ条件とする。
