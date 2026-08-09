# PMGS入力データ契約

## 対象

入力は`JPPM2026002`ディレクトリである。

入力ディレクトリは読み取り専用として扱い、ビルド中に作成、変更、削除を行わない。

## 実測したファイル構成

| データ群 | 形式 | 件数 | bytes | 主な用途 |
|---|---:|---:|---:|---|
| `CONCORDANCE` | CSV | 17 | 23,527,119 | FIとIPCの対応 |
| `FI/FI` | CSV | 9 | 9,519,200 | FIコードと階層 |
| `FI/FI_HB` | CSV | 8 | 34,033,166 | FIハンドブック日本語 |
| `FI/FI_HB_E` | CSV | 8 | 28,822,479 | FIハンドブック英語 |
| `FI/FI_KAISEI_DOC` | XML、XSL | 639 | 20,863,551 | FI改正文書 |
| `FI/FI_KAISEI_LINK` | CSV | 8 | 22,989 | FIと改正文書の接続 |
| `FI/FI_TEXT` | CSV | 9 | 19,572,862 | FI公式日本語 |
| `FI/FI_TEXT_E` | CSV | 9 | 17,383,888 | FI公式英語 |
| `FI/FI_THEME` | CSV | 8 | 6,190,701 | FIとFタームテーマの関係 |
| `FTERM/ADD_CODE` | HTML | 2 | 654,643 | 付加コード日本語 |
| `FTERM/ADD_CODE_E` | HTML | 2 | 139,177 | 付加コード英語 |
| `FTERM/FTERM` | CSV | 41 | 36,143,599 | Fターム日本語 |
| `FTERM/FTERM_E` | CSV | 41 | 36,606,838 | Fターム英語 |
| `FTERM/FTERM_KAISETSU` | CSV | 40 | 88,169,606 | Fターム解説日本語 |
| `FTERM/FTERM_KAISETSU_E` | CSV | 40 | 78,438,826 | Fターム解説英語 |
| `FTERM/THEME` | CSV | 1 | 338,358 | テーマ日本語 |
| `FTERM/THEME_E` | CSV | 1 | 269,320 | テーマ英語 |
| `IPC/IPC4_TEXT`から`IPC/IPC8U_TEXT` | CSV | 56 | 67,518,936 | IPC各版の公式本文 |
| `IPC_KAISEI` | HTML | 23 | 6,729,230 | IPC改正表 |
| `JUDGE` | CSV | 1 | 3,404 | 判定区分 |
| `REFERENCE/IPC_TEIGI` | PDF | 5,906 | 526,874,126 | IPC定義文書 |
| `COPYRGHT` | text | 1 | 22 | 権利表示 |

合計は6,870ファイル、1,002,622,042 bytes（956.175 MiB）である。

## 文字コードとパース

CSVはUTF-8 BOMの有無を吸収し、Python標準`csv`で改行を含むセルを読む。

FI改正XMLの宣言はShift_JISであり、通常は`lxml`へbytesを渡して宣言を尊重する。
通常の厳格解析が失敗し、CP932として厳格デコードと厳格XML解析の両方が成功した場合だけ、CP932互換経路を使う。

HTMLはbytesから解析し、本文、表、リンク、見出しを保持する。

PDFはPyMuPDFでページ単位に本文を抽出し、空ページと例外を`build_issue`へ記録する。

## 完全性

source manifestは相対パス、bytes、SHA-256、形式、データ群、parser、処理状態を1ファイル1行で記録する。

処理状態は`parsed`、`retained`、`failed`の三値に限定する。

同じ入力から生成した論理manifestは同じSHA-256にならなければならない。

全件プロファイルの行数、要素数、PDFページ数、既知例外は[source-profile.md](source-profile.md)に固定する。

## SQLite検索索引

分類本文と文書本文は、正規テーブルを正本として保持し、検索用にSQLite FTS5のtrigram仮想テーブルへ同じ本文と安定IDを登録する。

分類から関連文書の該当節を取得するため、`document_text(document_id, source_locator)`複合索引を持つ。これは公開値を増減させない物理索引である。

trigramは日本語文中の3文字以上の部分語を語境界に依存せず照合するために使う。1文字または2文字の検索語は索引の仕様上照合できないため、query層がescape済みリテラル部分一致へ限定して処理する。

検索結果はAI要約や意味類似度ではなく、公式本文の文字列一致である。
