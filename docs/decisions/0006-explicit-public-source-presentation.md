# ADR 0006: 公開出典表示をpolicyから必須生成する

- 状態: 採用
- 日付: 2026-08-09

## 文脈

旧実装のJSON source objectはattributionを持っていたが、HTMLとMarkdownは相対識別子とSHA-256だけを表示していた。

トップページと`llms.txt`も、PMGS本文を独自変換した非公式サービスであることを十分に示していなかった。

また、複数のsource policyを受け付けながら、個別source fileとpolicyの対応関係を表すschemaは存在しなかった。

この状態では、表示不足と権利条件の誤対応をfail closedで防げない。

## 決定

`publication-policy`の各sourceへ次のfieldを追加する。

- `owner`
- `source_url`
- `attribution`
- `processing_notice.ja`
- `processing_notice.en`
- `non_affiliation_notice.ja`
- `non_affiliation_notice.en`

HTML、Markdown、トップページ、`llms.txt`は、このpolicyから出典と表示を生成する。

JSON classification recordとdocument manifestのsource objectは、owner、source URL、attributionを持つ。

公開exportはpolicyのattributionを正本SQLiteの`COPYRGHT`と照合し、一致しない候補を生成しない。

public validatorは対象HTML、Markdown、トップページ、`llms.txt`に必須表示があることを検査する。

表示が一つでも欠けた場合は`notice_errors`を記録して不合格にする。

v1のpublication policyはsourceを一つだけ受け付ける。

複数sourceに対応する場合は、source fileとpolicy source IDの明示的なmappingを別のcontract changeとして設計する。

## 結果

人向けページとAI向け入口が同じ出典表示を持つ。

JSON clientもowner、原典案内URL、attributionを直接取得できる。

公開参照面がJPOまたはINPITの公式サービスであると誤認されるriskを下げる。

複数sourceを誤った一括attributionで公開するriskをfail closedで防ぐ。

policy変更は公開bytesとpolicy hashを変えるため、実データreleaseは新しいA/B exportと全件auditを必要とする。

## 不採用案

rendererへ固定文言を直接埋め込む案は、policyと表示が分離するため採用しない。

JSONだけにattributionを残す案は、人とweb retrieval clientが表示を確認できないため採用しない。

source fileとpolicyのmappingなしに複数sourceを許可する案は、安全な帰属を保証できないため採用しない。
