# ADR 0003：公開成果物を決定論的な版付きチャンクにする

- 状態：採用
- 日付：2026-08-08

## 文脈

約120万の分類概念と6,667文書を、Workerのリクエスト中にSQLite検索やHTML変換を行わず提供する必要がある。

グループを複数チャンクへ分けながら、分類の恒久URLを常にグループ先頭ページへ向けると、2チャンク目以降のfragmentへHTTPサーバーが到達できない。fragmentはHTTPリクエストへ送信されないためである。

また、ビルド時刻やローカルパスが成果物へ入ると、同じ入力から同じhashを再現できない。

## 決定

分類と文書は、版、lookup key、sequenceの安定順でJSONチャンクへ分ける。

JSONチャンクの既定上限は`262,144 bytes`（256 KiB）とする。[2026-08-08のworkerdベンチマーク](../verification/chunk-benchmark-2026-08-08.md)では261,600 bytesのfixtureが中央値7 ms、p95 9 ms、724,632 bytesではp95 11 msだった。1レコードまたは1文書節だけで上限を超える場合は、その1件を単独チャンクとして完全な本文を保持する。

分類の公開URLは次の形にする。

```text
/ja/classification/G06F3
/ja/classification/G06F3/002
/ja/fterm/4C083
/ja/fterm/4C083/002
/ja/ipc/4/G06F3
```

`001`だけチャンク番号を省略し、`002`以降はURLへ明示する。各分類のfragmentは、その分類が存在するチャンクURLへ付ける。

文書も同様に`001`を基底URL、後続を`/{chunk}`とする。JSON APIは文書manifestのsequence範囲から対象チャンクを選ぶ。

分類JSONチャンクは日本語と英語の公式値を一つの保存レコードへ保持する。Workerは`language`に一致する値だけを共通レコードへ射影する。これにより、API照会はグループmanifestとJSONチャンクの最大2回のR2取得で完了する。

`generated_at`は実行時刻を読まず、publication policyの`checked_at`午前0時UTCをrelease snapshot時刻として使う。実際の実行時刻は再現対象外のローカル検証reportだけへ記録できる。

絶対canonical URLを生成するため、exportは`base_url`を必須にする。ローカル負荷試験では予約済み`.example`ドメインを使用できるが、外部upload前には実ドメインで再生成する。

## 結果

- 同じDB、policy、base URL、chunk上限から同じ成果物hashを再現できる。
- Workerは利用者入力からR2 keyを直接作らず、manifestの範囲だけを選ぶ。
- 分割後もHTML、Markdown、sitemapから全分類へ到達できる。
- ドメイン変更時は公開成果物の再生成が必要である。
- 初版の公開全文検索APIは設けない。
- ローカルworkerd時間は本番CPU課金時間ではないため、deploy後のCPU観測は別のlive運用ゲートに残る。
