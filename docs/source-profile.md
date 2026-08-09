# PMGS原資料プロファイル

## 目的

`JPPM2026002`の実際の構造を推測ではなく全件走査で確定し、adapter、SQLite、完全性検査の根拠にする。

プロファイルは2026年8月8日に読み取り専用で実施した。原資料は変更していない。

## CSV

CSVは297ファイル、4,289,667論理行で、全ファイルを`utf-8-sig`として厳格に読めた。

| データ群 | 論理行数 | 通常列数 |
|---|---:|---:|
| `CONCORDANCE` | 500,577 | 4 |
| `FI/FI` | 190,384 | 5 |
| `FI/FI_HB` | 323,264 | 5 |
| `FI/FI_HB_E` | 323,364 | 5 |
| `FI/FI_KAISEI_LINK` | 636 | 2 |
| `FI/FI_TEXT` | 192,688 | 7 |
| `FI/FI_TEXT_E` | 192,827 | 7 |
| `FI/FI_THEME` | 187,597 | 5 |
| `FTERM/FTERM` | 411,383 | 5 |
| `FTERM/FTERM_E` | 411,383 | 5 |
| `FTERM/FTERM_KAISETSU` | 506,558 | 4 |
| `FTERM/FTERM_KAISETSU_E` | 507,014 | 4 |
| `FTERM/THEME` | 2,973 | 8 |
| `FTERM/THEME_E` | 2,973 | 8 |
| `IPC/IPC4_TEXT` | 71,210 | 6 |
| `IPC/IPC5_TEXT` | 76,046 | 6 |
| `IPC/IPC6_TEXT` | 79,613 | 6 |
| `IPC/IPC7_TEXT` | 79,349 | 6 |
| `IPC/IPC7E_TEXT` | 71,723 | 6 |
| `IPC/IPC8B_TEXT` | 71,516 | 9 |
| `IPC/IPC8U_TEXT` | 86,497 | 11 |
| `JUDGE` | 92 | 2 |

既知の列数例外は、`FTERM/FTERM_E`の13行と`FI/FI_KAISEI_LINK`の2行である。
いずれも引用符が不足した説明中のカンマが追加列として読まれる形であり、元のセル配列は`source_record`へそのまま保存する。
Fターム英語は先頭3列と末尾1列を固定し、中間列をカンマで再結合して説明本文を復元する。
FI改正リンクは先頭列をコード、それ以降を説明として扱う。

## FI改正XML

- 638ファイルすべてのrootは`data`だった。
- `infor`要素は110,590件だった。
- 主な要素は`FI` 110,590、`title` 84,873、`trans` 41,837、`newtitle` 25,717、`oldtitle` 25,716だった。
- 全638ファイルが`Shift_JIS`を宣言していた。
- 637ファイルは宣言どおりの厳格解析で成功した。
- `B60T.xml`だけはCP932拡張文字を含むため、通常解析失敗後のCP932厳格デコードと厳格XML解析で成功した。
- XML構造の修復を行う`recover=True`は使用しない。

## HTML

- `FTERM/ADD_CODE`と`FTERM/ADD_CODE_E`は各2ファイルで、テーマ別の付加コード表だった。
- `IPC_KAISEI`は23ファイルで、うち22ファイルに旧IPC、旧発効日、新IPC、新発効日の表があった。
- table rowを監査用`source_record`へ保存し、表示用本文と分類関係を別に生成する。

## IPC定義PDF

- 5,906ファイルをすべて開けた。
- 合計7,299ページ、抽出本文2,202,313文字だった。
- ファイル単位の失敗は0件だった。
- 本文が空のページは41ページだったが、本文が全くないファイルは0件だった。
- 最小ファイル本文は48文字、最大は25,111文字だった。
- 空ページはwarningとして記録し、ページ番号を欠番のまま保つ。

## 実データbuild結果

- SQLite：3,246,669,824 bytes（文書locator索引追加前は3,167,748,096 bytes）
- SHA-256：`A4243ED75E1E3A32E748864F47AD21D47F543FF0B3B8A31E3D32392C899FCC33`（追加前は`C28D6D77A1E54C493A0BAD139C8578CA5D13038692E5DB46AF84E51842DDE244`）
- 検索索引：SQLite FTS5 trigram、`document_text(document_id, source_locator)`
- source：6,870
- 監査用`source_record`：4,430,638
- 概念：1,207,960
- 分類本文：1,746,489
- 文書：6,667
- 文書節：1,665,758
- relation：1,863,942
- build error：0
- warning：PDF空ページ41

対応表、改正、解説だけに現れて現行分類表に存在しないコードは、原資料を失わず現行件数を過大にしないよう`*_reference`概念として区別した。
