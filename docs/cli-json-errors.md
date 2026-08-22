# CLI JSONエラー契約

PMGS ReferenceのCLIをCI、シェル、AIエージェントから利用する場合、機械可読な実行では、失敗時も標準出力をJSON object 1件に固定する。

## JSONモードになる条件

次の照会系コマンドは、`--json`を指定した場合にJSONモードになる。

- `setup`
- `lookup`
- `search`
- `document`
- `doctor`

次のコマンドは正常時からJSON固定であるため、`--json`を指定しなくてもparse errorとruntime errorを同じJSON envelopeで返す。

- `inventory`
- `build`
- `validate`
- `agent-kit`
- `install-agent-skill`
- `export-public`
- `validate-public`
- `audit-public`

## 失敗時のenvelope

```json
{
  "schema_version": "1.0",
  "status": "failed",
  "command": "validate",
  "error": {
    "code": "FILE_NOT_FOUND",
    "message": "requested file was not found"
  }
}
```

契約は次のとおり。

- 標準出力へJSON objectを1件だけ出力する。
- JSON failure時の標準エラー出力は空にする。
- 終了コードは非0のまま維持する。引数エラーは2、runtime errorは原則1である。
- `schema_version`、`status`、`command`、`error.code`、`error.message`を安定fieldとする。
- `error.code`は例外型と失敗領域から決定する。代表例は`ARGUMENT_ERROR`、`FILE_NOT_FOUND`、`CURRENT_POINTER_ERROR`、`DATABASE_ERROR`、`BUILD_FAILED`、`IO_ERROR`である。
- `error.message`は機械利用向けの固定された概要であり、例外の生メッセージではない。
- ローカル絶対path、credential、stack trace、SQLiteの生error、PMGS本文をJSON errorへ含めない。

## 成功・業務上の否定結果との区別

共通error envelopeは、処理を実行できなかった場合にだけ使う。次は既存の通常payloadを維持する。

- `lookup --json`の`not_found`、`version_not_found`、`not_valid_at_release`
- `validate`の`valid: false`
- `validate-public`の検証不一致
- `doctor --json`が返す構造化された診断結果

これらはdomain resultであり、CLI facadeが共通errorへ書き換えない。呼び出し側はpayloadと終了コードの両方を確認する。

## 人向けモード

JSONモードでない場合は従来のhelp、進捗、人向け出力を維持する。失敗は読みやすいtextを標準エラー出力へ書き、非0で終了する。

## 例

```powershell
pmgs lookup fi "G06F3/048" --json
pmgs doctor --timeout-seconds 30 --json
pmgs validate C:\path\to\pmgs.sqlite
```

JSON consumerは、標準出力をtextとJSONの二重parserへ分岐させず、常にJSONとしてparseする。診断に必要な機密性のない詳細が不足する場合は、人向けモードまたは別途保存した検証reportを使用する。
