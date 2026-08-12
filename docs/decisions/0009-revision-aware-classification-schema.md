# ADR 0009: 分類概念と版ごとの改訂を分離する

- 状態: 採用
- 日付: 2026-08-12

## 文脈

schema v1はrelease、scheme、edition、normalized codeを`concept`の一意な識別子とし、
本文、有効期間、IPC version indicatorも同じconceptへ接続していた。

この形では、同じIPCコードに複数のversionがある場合に本文と有効期間が混在する。
IPC改正表の旧版と新版も同じconceptへ解決されるため、版をまたぐ改正を正確に表現できない。
また、FI改正資料にだけ現れる過去コードは現行FI表に存在せず、文書リンクと改正関係を
黙って失う可能性があった。

## 決定

SQLiteを`user_version=2`、分類recordを`schema_version=2.0`へ更新する。

- `concept`は分類体系、edition、コード、正規化コード、`canonical`または
  `reference_only`の区分だけを表す。
- `concept_revision`はversion indicator、有効期間、level、構造上のsequence、source lineageを表す。
- 本文と属性はrevisionへ接続し、本文行ごとのsequenceは`concept_text`へ保存する。
- IPC改正はrevision間の関係と文書リンクとして保存する。
- FI改正資料にだけ現れる非空コードは`reference_only` conceptとして保存する。
- FI改正文書は改正要素の元コードへ接続し、変換先コードは`amended_to`関係の終点として保存する。
- `reference_only`は通常検索、coverage、sitemap、現行分類一覧へ含めない。
- releaseの基準日は認識済み分類CSVのファイル名から導出し、一意でなければ構築を拒否する。
- IPCのversion省略照会は、release基準日に有効な唯一のrevisionだけを返す。
  有効revisionがない場合や複数ある場合に別versionを推測しない。
- JPPM2026002では基準日に有効revisionがないIPC 8U codeは2,395件であり、そのうち
  複数revisionを持つcodeは44件である。単一revisionの2,351件も旧版へfallbackしない。
- schema v1からのin-place migrationは提供せず、元PMGSからschema v2を再構築する。

分類階層はconcept間の関係として保持する。同一conceptのrevisionごとに導出した親が一致しない場合は、
一つへ推測せずbuild errorにする。

IPC原資料では、同一code・version・有効期間・levelに複数の本文行があり、各行のsequenceが異なる。
この値はrevisionの競合ではなく本文行順を表すため、`concept_text.sequence_number`へ保持する。
IPCの`concept_revision.sequence_number`は空とし、有効期間とlevelの不一致は引き続きbuild errorにする。
FIとFタームの構造sequenceはrevisionの属性として厳密に照合する。

Fタームのtheme、level、sequence、parentは日本語`FTERM/THEME`と`FTERM/FTERM`を
構造正本とする。英語`FTERM/THEME_E`と`FTERM/FTERM_E`は、同じコードとsequenceで
解決した日本語revisionへ公式英語本文と言語別属性を追加するローカライズ元として扱い、
独自のconceptや階層を構築しない。英語側の未知コードと`FTERM_E`のsequence不一致は
build error、`FTERM_E`のdepth差は原行を`source_record`へ保持したうえでwarningにする。
`THEME_E`のsequenceは日本語側と異なる実レコードがあり、構造入力に採用せずwarningとして
保持する。

## 公開成果物

公開exportは、基準日応答と明示version応答を事前生成する。
同じコードの全revisionは同じ分類bundleへ入れ、Workerは有効期間を計算せず、
利用者が指定したselectorに対応する生成済みrecordだけを返す。

同じコードのbundleはJSON chunkをまたがせない。単一bundleが256 KiBを超える場合は
公開exportを拒否し、正常照会の最大2回のR2読み取りを維持する。

## 互換性

v0.4.0のquery層はschema v1 DBを照会せず、`pmgs setup SOURCE`による再構築を案内する。
setupは既存v1 DBとpointerを保持し、schema v2候補のvalidationとstdio doctorが成功した後だけ
`current.json`を原子的に切り替える。

## 結果

IPC本文と有効期間をversion単位で照会でき、改正関係が同一コードの自己関係へ潰れない。
FI改正資料にしかないコードも、現行分類と誤表示せずに根拠付きで参照できる。

schema、Python API、CLI、MCP、公開JSON、OpenAPI、Workerは同じreleaseで更新し、
旧schemaの全量監査結果を新版へ継承しない。
