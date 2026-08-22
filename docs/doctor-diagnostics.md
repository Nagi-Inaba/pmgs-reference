# `pmgs doctor`の有界stdio診断

`pmgs doctor`と`pmgs setup`の有効化前診断は、同じ読み取り専用stdio MCPサーバーを実際に起動し、次の3ツールを一度ずつ呼び出す。

- `lookup_classification`
- `search_pmgs`
- `get_pmgs_document`

診断用の分類、検索語、文書IDは対象SQLiteから決定的に選ぶ。レポートへ本文全量やローカル認証情報は保存せず、各ツールの上限付き構造化応答だけを記録する。

診断全体の既定上限は30秒である。起動、初期化、ツール列挙、各ツール呼び出し、終了処理のいずれかが上限を超えた場合は、子stdio処理をキャンセルして回収し、`MCP_TIMEOUT:<stage>`を返す。タイムアウトしたSQLiteを現行版として有効化しない。

診断前後ではSQLiteのSHA-256を比較する。管理ディレクトリを使う場合は、`current.json`の参照先とidentityが診断中に変化していないことも確認する。
