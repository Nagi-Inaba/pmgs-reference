# 登録条件と公開形態

- 最終確認日: 2026-08-09
- 対象release: `JPPM2026002`
- 文書の役割: 実装上の公開境界と確認資料の記録

## 結論

PMGS Referenceは、JPOの登録制一括ダウンロードサービスから正規に取得したPMGSパッケージを入力として使う設計である。

実データを処理するoperatorは、自らの登録、取得経緯、適用条件を公開候補の生成前に確認しなければならない。

このrepositoryは登録申込書、登録ID、password、連絡先その他の登録証明を保存せず、第三者の登録状態を証明しない。

公開成果物は分類または文書単位の情報提供面に限定する。

元archive、元package、正本SQLite、一括JSON、実質的なbulk dead copyは公開配布しない。

## 直接適用する資料

[特許情報の一括ダウンロードサービス利用規約](https://www.jpo.go.jp/system/laws/sesaku/data/document/download/terms_of_use_bulk_data_download_service.pdf)を取得データの提供境界に使う。

同規約第2条は、取得データの利用目的として情報提供サービス、研究、その他の産業財産権に関係する目的を挙げている。

同規約第4条は、JPOとINPITの承諾なく取得データを単純複製し、そのデータを第三者へ譲渡する行為を禁止している。

同規約第9条は、指定方法で提供される過去分データにも規約を準用している。

これらの条項を実装上の根拠として、recordと文書単位の情報提供を許可し、bulk配布を禁止するfail-closed policyを採用する。

## 補助的に確認する資料

[特許情報取得APIの公式案内](https://www.jpo.go.jp/system/laws/sesaku/data/api-provision.html)は、2026-08-09時点で利用の手引き第2.0版を現行版、第1.4版を改訂前の版として掲載している。

API手引きは別サービスの資料であり、一括ダウンロードデータの利用許諾そのものとして扱わない。

改訂前の第1.4版は、一括ダウンロードサービスで作成した独自databaseを使う情報提供サービスに言及していた。

現行の第2.0版はその記載を残していないため、第1.4版の記載を現在の許諾根拠として使わない。

[パテントマップガイダンス旧版データの利用制限](https://www.jpo.go.jp/system/laws/sesaku/data/old_pmgs.html)は、第三者向けサービスでJPOのdatabase著作権を明示し、単純複製を原則認めないとしている。

この旧版ページは2000年10月以前の旧PMGSデータを対象とするため、`JPPM2026002`へ直接適用する規約とは扱わない。

## JPOウェブコンテンツの表示

[JPOウェブサイトの利用案内](https://www.jpo.go.jp/toppage/about/index.html)は、対象コンテンツを利用する際の出典表示と、編集または加工した場合の加工表示を求めている。

この一般案内を、保存したJPO公開資料とその抽出Markdownの表示に適用する。

一般案内のPDL1.0表示だけを根拠に、登録制PMGS package全体の利用条件を上書きしない。

PMGS公開ページには、JPOの原典案内URL、`Copyright (C) JPO 2026`、独自変換であること、JPOまたはINPITの公式サービスではないことを表示する。

帰属文字列はrelease内の`COPYRGHT`を正本とし、publication policyと一致しない場合は公開exportを開始しない。

この実装境界は公開可否に関する法律判断を代替せず、operatorは自らに適用される登録条件と公開内容をreleaseごとに確認する。

## 保存した公開証跡

| 資料 | 状態 | bytes | SHA-256 |
| --- | --- | ---: | --- |
| [一括ダウンロードサービス利用規約](https://www.jpo.go.jp/system/laws/sesaku/data/document/download/terms_of_use_bulk_data_download_service.pdf) | 直接適用する資料 | 83,253 | `2F71C10C809A336E59359A3F5F2599A3B5B125DD3624417BB899BF8C860C50FC` |
| [特許情報取得API利用の手引き第2.0版](https://www.jpo.go.jp/system/laws/sesaku/data/document/api-provision/api_handbook_v2.0.pdf) | 現行の補助資料 | 388,401 | `98E6313686734E83CA5DCAF4E6FC9EDB6E68A25C5A82B8C9BFA596D8B5245C30` |
| [特許情報取得API利用の手引き第1.4版](https://www.jpo.go.jp/system/laws/sesaku/data/document/api-provision/api_handbook_v1.4.pdf) | 履歴資料 | 1,067,922 | `A82FF6B2D7CAC59559732E63CB41A5953548049EF3E105BC9F29849955B5F177` |

原本PDFと抽出Markdownは`docs/evidence/`へ保存する。

各Markdownは機械的にテキスト抽出した派生資料であり、正確な内容は原本PDFを優先する。

## publication policy

`config/publication-policy.yaml`は次の配信を有効にする。

- record単位のウェブ情報提供
- record単位のJSON API
- record単位のMCP照会
- 検索エンジンのindex
- AIによる質問回答時の参照

同policyは次の配信を無効にする。

- AI training向けbulk提供
- source archive download
- canonical database download

v1はsource policyを一つに限定する。

複数sourceの権利条件を安全に対応付ける契約が実装されるまで、複数source policyは受け付けない。

## 更新

新しい公開候補ごとに、規約URL、確認日、原本SHA-256、publication policy hashをrelease manifestへ固定する。

規約が変わった場合は既存releaseを上書きせず、差分確認後に次releaseのpolicyを更新する。

この文書は実装境界の記録であり、第三者向けの法律意見ではない。
