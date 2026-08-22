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

`tests/test_onboarding_contract.py`は、各READMEの未保有者向けsectionだけを切り出し、公式リンク、詳細文書、版directory、preflight commandがsection内に存在することを検証する。また、install commandがpreflightより前に現れることと、日本語・英語でcredentialおよびsource materialの境界が同等に記載されることを検証する。

## 検証状態

本記録と最新`main`を取り込んだheadに対してGitHub Actionsの全必須checkを実行する。hosted runが完了した後、run ID、pytest件数、failure、skip、Markdown link確認結果を追記し、その結果を最終マージ判定に使用する。
