# ADR 0005：全量公開ビルドを有界並列化する

- 状態：採用
- 日付：2026-08-08

## 文脈

実データは1,207,960概念、72,903公開グループ、6,667文書を持つ。
最初の逐次ビルドでは、小さいfileのcloseとdirectory作成が処理時間の大半を占め、約60グループ/分だった。
このまま2回生成と全件検査を行うと、release検証に不必要な長時間を要する。

高速化で公開順、JSON bytes、canonical URL、manifest、tree hashを変えてはならない。また、SQLite正本はread-onlyのままにする必要がある。

## 決定

- 最大1,000概念を一度にSQLiteから組み立て、完成レコードを元のグループへ戻す。
- グループと文書の独立したファイル書込みは32 workerで行う。metadataとsitemapは元の安定順で統合する。
- 同じwriter内で作成済みの親ディレクトリを記録し、同一親への`mkdir`を繰り返さない。
- export専用read-only接続はSQLite cache上限を1 GiB、mmap要求を2 GiB、temp storeをmemoryとする。
- 分類から関連文書節を引くjoinに合わせ、`document_text(document_id, source_locator)`複合索引を正本スキーマへ持たせる。
- exportのtree hashは、書込み時に取得済みのobject SHA-256から算出し、全ファイルを再読込しない。
- validatorは各ファイルを最大1回だけ読み、32 workerの有界windowでhash、parser、漏えい、HTML、coverage、tree hashを同時検査する。

## 再現性ガード

合成fixtureで次を自動検査する。

- 1概念単位・1 write workerの旧相当モードと、1,000概念・4 write workerの公開ツリー全bytesが一致する。
- exportが保持済みobject hashから出すtree hashと、独立validatorが実ファイルから出すtree hashが一致する。
- validatorの1 workerと4 workerで結果JSONが一致する。

## 結果

- 実データ30グループ・180 objectの書込みは、逐次12.952秒から32 worker 2.004秒へ短縮した。
- SQLite cacheとmmapは、異なる2窓のレコード組立をいずれも約2倍へ短縮した。
- 複合索引がないDBは論理互換だが、全量公開ビルドの性能要件を満たさない。
- 並列完了順は公開manifestとsitemap順へ影響しない。
- 最大1 GiBまでSQLite cacheが成長し得るため、全量exportはメモリ余裕のあるビルド環境で行う。
- 外部R2 uploadやWorker deployを並列化・自動実行する決定ではない。

測定条件と不採用値は[全量export性能検証](../verification/export-performance-2026-08-08.md)へ記録する。
