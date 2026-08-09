# 全量export性能検証

- 測定日: 2026-08-08
- 対象: `JPPM2026002`から生成した読み取り専用SQLite
- 測定範囲: ローカルstorage上のpublic export

## 結論

逐次方式では約60 group/minであり、独立したA/B全量生成と全件検証に長時間を要した。

公開bytesを変えずに、record一括組立、有界並列write、SQLite read cache、生成時tree hash、1回読込validatorを採用した。

関連文書節queryには`document_text(document_id, source_locator)`複合indexを追加した。

最終方式は、合成fixtureで旧相当方式と全公開bytesが一致することを確認した。

## profile

実データ先頭10 groupの逐次生成をprofileした。

全体5.555秒の主な累積時間は次のとおりだった。

| 処理 | 秒 |
| --- | ---: |
| `_write_group` | 4.244 |
| 60 fileの`write_bytes` | 4.176 |
| file close | 2.988 |
| `mkdir` | 1.137 |
| `load_group_records` | 1.312 |
| HTML render | 0.041 |

描画計算ではなく、小さいfileのI/Oが最大要因だった。

## 採用した測定

### record一括組立

30 group、507 conceptで、1 groupずつの組立は7.271秒、一括組立は6.589秒だった。

生成record bytesは一致した。

### write worker

同じ30 group、180 objectを同じstorageへ書いた。

| worker | 秒 | 逐次比 |
| ---: | ---: | ---: |
| 1 | 12.952 | 1.00x |
| 8 | 5.526 | 2.34x |
| 16 | 3.297 | 3.93x |
| 32 | 2.004 | 6.46x |

### SQLite read-only接続

既定値は`cache_size=-2000`、`mmap_size=0`だった。

1 GiB cacheと2 GiB mmapを、順序を反転した二つのwindowで比較した。

| concept | 既定 秒 | 調整後 秒 | 改善 |
| ---: | ---: | ---: | ---: |
| 2,402 | 37.551 | 18.126 | 2.07x |
| 406 | 17.855 | 8.867 | 2.01x |

### 関連文書節query

最初の52 group、985 conceptをquery群ごとに計測した。

| query群 | 秒 |
| --- | ---: |
| concept、text、property、relation、child、document | 0.031 |
| linked document text | 9.635 |

`linked document text`は`document_id`と`source_locator`を完全一致させる一方、旧schemaには`document_id, sequence_number`indexしかなかった。

複合index追加後、同じlinked queryは0.0108秒、完成record mapは0.0679秒だった。

詳細は[文書locator indexの検証](document-text-index-2026-08-08.md)に記録した。

## 不採用

- 2 GiB cacheと4 GiB mmap要求は安定した改善がなかった。
- SQL ID batch 2,000はbatch 500に対して安定した改善がなかった。
- HTMLまたはMarkdownの削除は公開契約を変えるため採用しなかった。
- Worker request中の動的renderはCPU上限と決定性を悪化させるため採用しなかった。

## 正しさの検査

- 合成fixtureの旧相当方式と新方式で公開tree全bytesが一致した。
- exportが保持済みobject hashから計算したtree hashと、独立validatorのtree hashが一致した。
- validatorの1 workerと4 workerで結果JSONが一致した。
- SQLiteはread-only接続を維持した。
- 並列完了順はmanifestとsitemapの順序へ影響しなかった。

この記録はローカルwall-clockであり、R2 upload時間または本番Worker CPU timeを示さない。
