# 検証記録

このdirectoryは、測定時点の入力、実装、公開契約に対する検証結果を保存する。

検証記録は履歴証拠であり、後日のschemaまたはpolicy変更後も自動的に現在releaseの証拠にはならない。

## 現在の境界

2026-08-09に公開source schemaと表示契約を変更した。

変更内容はowner、JPO原典案内URL、attribution、加工表示、非公式サービス表示の必須化である。

`public-release-2026-08-08.md`と`public-release-audit-2026-08-08.json`は、旧表示契約に対する履歴記録として保持する。

現在契約の実データA/B export、全件validator、release auditは、[2026-08-09の実データ公開候補検証](public-release-2026-08-09.md)で合格した。

機械可読な監査結果は[2026-08-09のrelease audit](public-release-audit-2026-08-09.json)へ保存した。

合成fixtureを使うrepository全検査とWorker回帰検査も、2026-08-09の現在契約で合格している。

現在の状態は[現在の状態](../current-status.md)を参照する。
