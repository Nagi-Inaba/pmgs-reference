# JSONチャンク上限ベンチマーク 2026-08-08

## 結論

公開exportの既定JSONチャンク上限を`262,144 bytes`（256 KiB）に固定する。

この値は、ローカルworkerdとR2 simulatorを含むend-to-end wall-clockで、261,600 bytesのfixtureが9回の中央値7 ms、p95 9 msだったことを根拠にした保守的な上限である。724,632 bytesではp95 11 msとなったため、従来候補の512 KiBは採用しない。

ローカルwall-clockはCloudflare本番のCPU課金時間そのものではない。本番deploy後はWorkers observabilityのCPU timeを別途監視する。

## 条件

- Node.js：`v22.19.0`
- Wrangler：`4.120.0`
- workerd compatibility date：`2026-08-06`
- `@cloudflare/vitest-pool-workers`：`0.20.3`
- 各サイズ：warm-up 1回、計測9回
- 照会対象：chunk末尾のFI record
- R2 read：全試行2回
- 計測範囲：Worker呼出し、R2 simulator、JSON parse、schema guard、record検索、response JSON decode

## 実測

| records | serialized bytes | median ms | p95 ms | R2 reads |
|---:|---:|---:|---:|---:|
| 128 | 180,888 | 6 | 7 | 2 |
| 185 | 261,600 | 7 | 9 | 2 |
| 256 | 362,136 | 8 | 9 | 2 |
| 512 | 724,632 | 10 | 11 | 2 |
| 1,024 | 1,449,720 | 15 | 16 | 2 |
| 2,048 | 2,903,800 | 25 | 26 | 2 |

実行コマンド：

```powershell
Set-Location worker
npm run benchmark:chunks
```

ベンチマークは`worker/test/chunk-size.benchmark.spec.ts`に保存し、通常のCI時間判定とは分離した。機能契約としては全サイズで200、正しい末尾record、`Server-Timing: pmgs-r2;desc="2 reads"`を検査する。

## 運用判断

- exportは通常recordを256 KiB以下へ分割する。
- 1 recordまたは1文書節だけで上限を超える場合は欠落させず、単独oversized chunkとして記録する。
- Workerのhard guardは8 MiBのまま残し、異常に大きい公開JSONは503へfail closedする。
- 全量export reportの`oversized_chunk_count`と最大object bytesを公開前監査で確認する。
- 本番CPUが無料枠の目標を超える場合は、上限をさらに下げて成果物を再生成する。R2側で既存版を破壊的に再分割しない。
