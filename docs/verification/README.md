# 検証記録

このdirectoryは、測定時点の入力、実装、公開契約に対する検証結果を保存する。

検証記録は履歴証拠であり、後日のschemaまたはpolicy変更後も自動的に現在releaseの証拠にはならない。

## 現在の境界

[v0.4.0の正確性検証](v0.4-correctness-2026-08-12.md)は、schema v2の全量A/B再構築、
公開export、AI client評価、release gateを一つの記録へまとめる。

未観測のlive挙動は自動試験の成功で代替せず、`not_observed`の理由と、その状態を受容した所有者判断の適用範囲を同じ記録へ明示する。source統合の判断と、tag、package、Web deployなどの外部公開Holdを分けて記録する。

2026-08-10に日本語topと日本語`llms.txt`を既定にし、英語topと英語`llms.en.txt`を切替先として追加した。

この入口変更後の契約は合成fixtureによるrepository全検査とWorker回帰検査で検証した。実データ全量A/B監査は、第三者が実originでWeb公開する場合に再実行する。

`public-release-2026-08-08.md`と`public-release-audit-2026-08-08.json`は、旧表示契約に対する履歴記録として保持する。

[2026-08-09の実データ公開候補検証](public-release-2026-08-09.md)は、owner、JPO原典案内URL、attribution、加工表示、非公式サービス表示を必須化した直前契約に対する全量A/B監査である。

機械可読な監査結果は[2026-08-09のrelease audit](public-release-audit-2026-08-09.json)へ保存した。

2026-08-09のobject countとtree hashを、2026-08-10の現行Web入口契約のrelease hashとして扱わない。

現在の状態は[現在の状態](../current-status.md)を参照する。
