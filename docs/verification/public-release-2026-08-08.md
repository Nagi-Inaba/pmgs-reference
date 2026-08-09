# 実データ公開候補のリリース検証（2026-08-08）

> この記録は2026-08-08時点の旧公開表示契約に対する履歴証拠である。
> 2026-08-09に出典、加工表示、非公式サービス表示の契約を変更したため、本文の`ready=true`は現在契約のrelease readinessを示さない。

## 結論

`JPPM2026002`の実データから独立した公開ツリーを2回生成し、両方の全ファイル検査と再現性監査を完了した。ローカル公開候補として`ready=true`、失敗0件である。

この判定は、公開成果物、ローカル照会面、Worker bundleを再現し、外部公開直前までの検査を通したことを意味する。R2 upload、Worker deploy、ドメイン設定、PyPI公開、Git pushは実施していない。検証時のoriginは`https://pmgs-reference.example`であるため、実公開時は確定したoriginを指定してA/B生成と同じ監査を再実行する。

機械可読な監査結果は[public-release-audit-2026-08-08.json](public-release-audit-2026-08-08.json)へ保存した。

## 固定した入力

| 項目 | 値 |
| --- | --- |
| release | `JPPM2026002` |
| source manifest SHA-256 | `96AA322D8D916406F4166FE1CFC9F6A1B749D09AFFB82EACD7B6557ECC215B52` |
| SQLite bytes | 3,246,669,824 |
| SQLite SHA-256 | `A4243ED75E1E3A32E748864F47AD21D47F543FF0B3B8A31E3D32392C899FCC33` |
| JSON chunk上限 | 262,144 bytes |
| generated at | `2026-08-08T00:00:00Z` |

## A/B生成結果

AとBの13個のexport report項目はすべて一致した。

| 項目 | A | B |
| --- | ---: | ---: |
| group | 72,903 | 72,903 |
| classification chunk | 78,567 | 78,567 |
| document | 6,667 | 6,667 |
| document chunk | 8,679 | 8,679 |
| object | 395,342 | 395,342 |
| bytes | 10,120,012,760 | 10,120,012,760 |
| oversized chunk | 0 | 0 |
| 観測所要時間 | 5,910.1秒 | 5,739秒 |

- tree SHA-256：`0F14A98F4E7BE90E7D44CBC5C89B15E99E8DBED84032B79E3C04BA0486B1E4A4`
- release manifest SHA-256：`8573DB76C2A4F002263E497EFFF0DB0BA513EF96E376CFC05CCB254A2F3BB906`
- chunk object：87,246件
- 最大chunk：262,144 bytes
- 最大object：`releases/JPPM2026002/manifest.json`、79,072,522 bytes

## 全ファイル検査

`validate-public`はAを1,302.2秒、Bを1,460.2秒で検査し、両方とも次の結果だった。

- `valid=true`
- object 395,342件、10,120,012,760 bytes
- tree SHA-256はexport reportと一致
- missing、unexpected、metadata、parse、forbidden file、leakage、HTML、coverage errorはすべて0件

最初のA検査では、JSON中の正規な改行escapeをWindowsパスと誤認した13件を検出した。検査器を「JSON上の二重backslashまたはslashを伴う絶対パス」だけに限定し、実際のWindows・Unixパスを検出する回帰テストを追加したうえでA/Bを全件再検査した。上記は修正後の結果である。

## 再現性・方針監査

`pmgs audit-public`でSQLite、A/B root、export report 2件、validation report 2件、期待hashを照合した。25条件はすべて`true`だった。

- A/Bは別rootで、export reportとvalidation reportが一致
- 両manifestのhash、release、生成条件、object数、bytes、coverageが一致
- SQLiteのapplication ID、release、schema、source manifest、SHA-256が一致
- 全chunkが256 KiB以下で、超過0件
- object key重複0件
- 公開方針の実ファイルhashがmanifestと一致
- Web、API、MCP、検索、AI入力は許可、AI学習、原資料一括download、正本DB downloadは不許可

監査結果は`ready=true`、`failures=[]`だった。

## コードとWorkerの最終ゲート

Python側は次を通した。

- `uv lock --check`
- `uv run --frozen ruff check .`
- `uv run --frozen ruff format --check .`
- `uv run --frozen mypy src`
- `uv run --frozen pytest -q`：39件成功
- `uv build`：sdistとwheel生成成功

Worker側はNode.js 22環境で`npm ci`後に`npm run verify`を通した。

- Wrangler生成型同期、TypeScript typecheck、oxlint成功
- workerd routeテスト23件、WebMCPテスト3件成功
- Worker dry-run bundle：34.75 KiB、gzip 8.21 KiB
- `npm audit --audit-level=high`：脆弱性0件

tracked fileに秘密鍵、代表的なAWS・GitHub・OpenAI token、credential入りURL、秘密情報らしいファイル名は見つからなかった。10 MiBを超えるtracked fileは0件で、実データSQLiteや原資料archiveはリポジトリへ含めていない。tracked CSV 19件は合成テストfixtureだけである。

## 残る境界

索引追加前の全DB integrity検査は成功した。索引追加後は、変更対象の`document_text`と索引、外部キー、件数、回帰基準を検査して成功したが、全DB `pmgs validate`は1,804秒でtimeoutした。このため索引追加後の「全DB integrity完了」とは扱わない。詳細は[文書locator索引の検証](document-text-index-2026-08-08.md)に記録した。

WebMCP対応実ブラウザでの手動smokeは任意確認として残る。通常HTML、Markdown、JSON API、OpenAPI、feature detection、Worker bundleの合格判定とは分離している。

外部公開時は、実originを確定し、A/Bを新規生成して同じ全件検査と監査を通した後、R2 upload、upload後hash検査、Worker deploy、本番smokeの順に進める。
