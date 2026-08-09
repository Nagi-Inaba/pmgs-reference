# 実データ公開候補のリリース検証（2026-08-09）

## 結論

`JPPM2026002`の実データから、現在の出典表示契約に従う独立した公開ツリーを2回生成した。

AとBの全399,025オブジェクトを個別に検査し、再現性と公開方針を横断監査した。

監査結果は`ready=true`、`failures=[]`であり、25条件はすべて`true`だった。

機械可読な監査結果は[public-release-audit-2026-08-09.json](public-release-audit-2026-08-09.json)へ保存した。

この結果は`full-data audited`までを示し、R2 upload、Worker deploy、ドメイン公開、PyPI公開、GitHub push、外部index登録は示さない。

検証用base URLは`https://pmgs.example.jp`であり、稼働中の本番URLではない。

## 固定した入力

| 項目 | 値 |
| --- | --- |
| release | `JPPM2026002` |
| source file | 6,870 |
| source bytes | 1,002,622,042 |
| source manifest SHA-256 | `96AA322D8D916406F4166FE1CFC9F6A1B749D09AFFB82EACD7B6557ECC215B52` |
| SQLite bytes | 3,246,669,824 |
| SQLite SHA-256 | `A4243ED75E1E3A32E748864F47AD21D47F543FF0B3B8A31E3D32392C899FCC33` |
| JSON chunk上限 | 262,144 bytes |
| generated at | `2026-08-09T00:00:00Z` |

## 正本SQLiteの検証

全DB検証は45.8秒で完了した。

`integrity_check=ok`、外部キー違反0、build error 0、`valid=true`だった。

正本は1,207,960概念、1,746,489分類本文、6,667文書、1,665,758文書節、4,430,638監査レコードを持つ。

Fタームテーマ2,929、Fターム411,383、FI 190,384、IPC 8U 82,540の回帰件数はすべて一致した。

FI、Fターム、IPC現行版8U、IPC旧版4、FI階層、分類検索、文書検索、IPC定義PDFページを実データで照会した。

照会前後のSQLite SHA-256は一致した。

## A/B生成結果

AとBの13個のexport report項目はすべて一致した。

| 項目 | A | B |
| --- | ---: | ---: |
| group | 72,903 | 72,903 |
| classification chunk | 79,322 | 79,322 |
| document | 6,667 | 6,667 |
| document chunk | 8,679 | 8,679 |
| object | 399,025 | 399,025 |
| bytes | 10,491,136,463 | 10,491,136,463 |
| oversized chunk | 0 | 0 |
| 観測所要時間 | 6,353.7秒 | 7,204秒超 |

- tree SHA-256: `BB192477B7A99380476A1C161A00C2AED3FBBFB1ABC331908F93A751631C43D3`
- release manifest SHA-256: `18D24AC9524B9D7F8430B00EAAAE40A73B82FA744C52370BA90BCD562DB13A49`
- chunk object: 88,001件
- 最大chunk: 262,144 bytes
- 最大object: `releases/JPPM2026002/manifest.json`、79,821,240 bytes

Bの実行ラッパーは7,204秒で終了コード124を返した。

同じ境界でBのexport reportとrelease manifestが完成し、Python残存プロセスは0件だった。

Bのexport reportはAと全13項目で一致し、その後の独立validatorとrelease auditも合格した。

このためBの成果物は完成候補として採用したが、ラッパーから正常終了時間は取得できなかった。

## 全ファイル検査

Aのvalidatorは1,303.7秒、Bのvalidatorは1,637.7秒で完了した。

両方とも`valid=true`で、object数、bytes、tree SHA-256がexport reportと一致した。

missing、unexpected、metadata、parse、禁止形式、漏えい、HTML、coverageの各errorは0件だった。

帰属、JPO原典案内URL、加工表示、非公式サービス表示を検査する`notice_errors`も0件だった。

## 再現性と公開方針の監査

`audit-public`でSQLite、A/B root、export report 2件、validation report 2件、期待hash、公開方針を照合した。

25条件はすべて`true`だった。

- A/Bは別rootで、export reportとvalidation reportが一致した。
- 両manifestのhash、release、生成条件、object数、bytes、coverageが一致した。
- SQLiteのapplication ID、release、schema、source manifest、SHA-256が一致した。
- 全chunkは256 KiB以下で、超過は0件だった。
- object keyの重複は0件だった。
- 公開方針の実ファイルhashがmanifestと一致した。
- Web、API、MCP、検索、AI質問時参照は許可されている。
- AI学習、一括元資料download、正本DB downloadは許可されていない。

監査結果は`ready=true`、`failures=[]`だった。

## 残る境界

公開候補ツリーと正本SQLiteはGitへ含めていない。

外部公開時は実originを確定し、新しい空の出力先へ同じA/B生成と全件監査を再実行する。

R2 upload後のhash検査、Worker deploy、本番URL smoke、sitemap、OpenAPI、検索index、AI検索からの発見性は未確認である。
