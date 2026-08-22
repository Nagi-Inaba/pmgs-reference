# PMGS acquisition onboarding verification — 2026-08-22

対象PR: #40

## 目的

PMGSをまだ保有していない利用者が、READMEだけから正規取得先、登録・認証の境界、安全な保存範囲、展開後の開始手順へ辿れることを確認する。

## レビュー対象

- 日本語・英語READMEに未保有者向け入口がある。
- JPO公式の一括ダウンロードサービスと利用規約へ1クリックで到達できる。
- repositoryが登録、認証、自動downloadを代行しないことを明示する。
- credential、申込書、source ZIP、展開後原資料、生成SQLiteをGitHub、Issue、外部AIへ送らないよう導入前に警告する。
- ZIP展開後に`JPPM`と数字からなる版directoryを確認し、write-free preflightへ進む。
- `uv tool install pmgs-reference`の導入案内がpreflight commandより前に表示される。
- 詳細な取得条件と公開境界を`docs/registered-use-terms.md`へ委譲する。

## 契約テスト

`tests/test_onboarding_contract.py`は、各READMEの未保有者向けsectionだけを切り出し、公式リンク、詳細文書、版directory、preflight commandがsection内に存在することを検証する。また、install commandがpreflightより前に現れること、日本語・英語でcredentialおよびsource materialの境界が同等に記載されること、内部リンク先の文書が存在することを検証する。

## Hosted CI evidence

commit `ebc0ba170189a9730ca36874c976ce8d47956920`をGitHub Actions CI run `32568937248`（run #274）で検証した。

### Python 3.12 on Ubuntu

- repository boundary: 186 candidate files、違反なし
- Ruff check: success
- Ruff format check: `102 files already formatted`
- mypy: `Success: no issues found in 29 source files`
- pytest: `249 passed, 5 skipped in 31.93s`
- wheel / sdist build: success

skip 5件はWindows固有の既存契約であり、本変更固有のfailureまたはskipは0件だった。

### Full matrix

次を含む同runの全jobが成功した。

- Python 3.12 / 3.14 on Ubuntu、Windows、macOS
- Python 3.13 on Ubuntu
- installed wheel on Ubuntu、Windows、macOS
- installed wheel on Python 3.13
- Cloudflare Worker on Node 22
- synthetic determinism on Ubuntu、Windows、macOSとcross-OS compare

## 失敗と修正履歴

- CI run `32568775502`では、contract testにWindowsの例示pathをliteralで保持したためrepository boundaryが停止した。path separatorを実行時に組み立てるよう修正した。
- CI run `32568823658`では、repository boundaryとlintは成功したが、Ruff formatが1行の整形差分を検出した。formatterが要求する形へ修正した。
- run #274で上記の修正後に全matrixが成功した。

## Link check

- `README.md`と`README.en.md`から参照する`docs/registered-use-terms.md`の存在をcontract testで確認した。
- JPOの一括ダウンロードサービスURLは検索index上で公式ページとして確認でき、そのページから利用規約PDFへの案内も確認できた。
- JPOは自動fetchへ403を返したため、今回の自動確認ではPDF本文の取得までは観測していない。URLの出典と内容契約はrepository内に保存済みのJPO公開証跡と`docs/registered-use-terms.md`へ委譲する。

## 最終判定

本記録を追加した最新headに対してrequired CIを再実行し、その全成功を最終マージ条件とする。
