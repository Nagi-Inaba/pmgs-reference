# PMGS Reference documentation

利用目的に応じて、次の文書から参照する。

## 導入とローカル利用

- [正規PMGSからの導入とAIクライアント接続](local-agent-kit.md) / [English](local-agent-kit.en.md)
- [Python・CLI・stdio MCPの参照契約](local-interfaces.md) / [English](local-interfaces.en.md)
- [CLI JSONエラー契約](cli-json-errors.md) / [English](cli-json-errors.en.md)

## 公開APIと運用

- [公開HTTP API](public-api.md) / [English](public-api.en.md)
- [release運用](release-runbook.md)
- [GitHub公開チェックリスト](github-publication-checklist.md)

## 設計・データ境界

- [architecture](architecture.md)
- [data contract](data-contract.md)
- [current status](current-status.md)
- [registered use terms](registered-use-terms.md)

`cli-json-errors.md`は、CI、shell、AI agentがCLI failureを機械処理するときのstdout、stderr、exit code、error envelope、機密情報境界を定義する。通常の照会方法は`local-interfaces.md`を参照する。
