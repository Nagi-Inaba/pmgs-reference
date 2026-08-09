# 文書locator索引の実データ検証（2026-08-08）

## 結論

`document_text(document_id, source_locator)`索引を実データ正本へ追加し、分類に紐づく文書本文queryを9.635秒から0.0108秒へ短縮した。主要表の件数、回帰基準、外部キー、索引対象表の整合性は維持された。

## 変更前後

| 項目 | 索引追加前 | 索引追加後 |
| --- | --- | --- |
| bytes | 3,167,748,096 | 3,246,669,824 |
| SHA-256 | `C28D6D77A1E54C493A0BAD139C8578CA5D13038692E5DB46AF84E51842DDE244` | `A4243ED75E1E3A32E748864F47AD21D47F543FF0B3B8A31E3D32392C899FCC33` |
| `document_text` index | `(document_id, sequence_number)` | 左記＋`(document_id, source_locator)` |

索引は`BEGIN IMMEDIATE` transaction内で作成し、4.913秒でcommitした。SQLite `user_version=1`とデータ契約`1.0`は、論理表・列・レコード形式を変えていないため維持した。

## query検証

`EXPLAIN QUERY PLAN`は次を返した。

```text
SEARCH document_text USING INDEX document_text_locator_idx (document_id=? AND source_locator=?)
```

先頭52グループ・985概念の同一queryでは次の結果だった。

| 項目 | 追加前 | 追加後 |
| --- | ---: | ---: |
| linked document text | 9.635 s | 0.0108 s |
| linked rows | 1,476 | 1,476 |
| 完成record map | 約9.7 s | 0.0679 s |

## 整合性

- `PRAGMA integrity_check('document_text') = ok`（3.899秒）
- `PRAGMA foreign_key_check`：0件
- `document_text`表：1,665,758件
- `document_text_locator_idx`経由count：1,665,758件
- build error：0件
- source 6,870、source record 4,430,638、concept 1,207,960、concept text 1,746,489、document 6,667、document link 1,399,695
- Fタームテーマ2,929、Fターム411,383、公開FI 190,384、IPC 8U 82,540の全回帰基準一致

索引追加後の全DB `PRAGMA integrity_check`を含む通常の`pmgs validate`は1,804秒でtimeoutし、成功reportは生成されなかった。
索引追加前の全DB検証は`integrity_check=ok`だった。
索引追加後は、新たに変更された`document_text`とそのindexを対象指定して`ok`を確認した。
したがって、この記録は索引追加後の全DB integrity check完了を証明しない。
