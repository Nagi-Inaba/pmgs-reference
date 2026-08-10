# 公開候補リリース手順

## 前提

このrunbookはローカルで公開候補を作り、外部公開直前まで検証する。

R2 upload、Worker deploy、ドメイン変更、PyPI公開、Git pushは含まない。

現在、管理者によるWeb公開は停止中である。第三者が外部公開を行う場合は、本runbookに加えて[Webセルフホストガイド](self-hosting.md)の費用、互換性、upload後全件照合、運用責任を確認する。

## 1. 入力を固定する

原資料を版付きディレクトリとして保持し、旧版を上書きしない。

`pmgs inventory`でmanifestとsummaryを生成する。

manifestのファイル件数、bytes、拡張子内訳、論理SHA-256を確認する。

JPO公式ページで一括ダウンロードサービス利用規約の現行URLを確認する。

`config/publication-policy.yaml`のevidence hash、確認日、owner、原典案内URL、加工表示、非公式サービス表示を確認する。

policyのattributionが入力releaseの`COPYRGHT`と完全一致することを確認する。不一致の場合、`export-public`は出力directoryを作る前に拒否する。

v1のsource policyが一つだけであることを確認する。

## 2. 正本を作る

`pmgs build`で一時SQLiteを生成する。

build完了後にschema、外部キー、FTS、件数、lineage、循環、失敗件数を検査する。

`document_text_locator_idx`が存在し、`document_id`と`source_locator`の完全一致query planで使用されることも確認する。索引なしのDBは論理的に読めても、全量exportには使用しない。

`pmgs validate DATABASE --report build/reports/validation-report.json`でDBハッシュを含む検査記録を生成する。

検査成功後だけ指定先へ原子的に置き換える。

## 3. ローカル参照面を検証する

`ruff check .`、`mypy`、`pytest`を実行する。

実データでFI、Fターム、IPC 8U、IPC旧版、階層、関連文書、PDFページ、日本語部分語検索を照合する。

`python.exe -m pmgs_reference.cli mcp --db DATABASE`をMCPクライアントからstdio起動し、tool 3件の列挙、正常応答、入力不正応答を確認する。

照会前後でSQLiteのSHA-256が変わらないことを確認する。

## 4. 公開成果物を作る

空の出力先を選び、実際の公開originを指定して次を実行する。

```powershell
pmgs export-public --db DATABASE --policy config/publication-policy.yaml --output build/public --base-url https://pmgs.example.jp --max-json-chunk-bytes 262144 --report build/reports/public-export.json
pmgs validate-public build/public --report build/reports/public-validation.json
```

`export-public`は既存出力先を上書きしない。失敗した出力先は検査用に残るため、原因確認後に別の空ディレクトリで再実行する。

分類、文書、coverage、release manifest、HTML、Markdown、JSON、OpenAPI、sitemapを生成する。

元ファイル、SQLite、一括JSON、ローカル絶対パス、ユーザー名、秘密情報が含まれないことを検査する。

すべてのHTML、Markdown、日英トップページ、日英`llms.txt`にattribution、原典案内URL、加工表示、非公式サービス表示があることを確認する。

公開JSONのsource objectにowner、原典案内URL、attributionがあることを確認する。

同じDB、policy、base URL、chunk上限で別ディレクトリへ2回生成し、公開ツリーSHA-256が一致することを確認する。

両方の`export-public` reportと`validate-public` reportが揃ったら、`pmgs audit-public`へDB、A/B root、4 report、期待DB SHA-256、期待source manifest SHA-256を渡す。

```powershell
pmgs audit-public `
  --db DATABASE `
  --first-root build/public-a `
  --second-root build/public-b `
  --first-export-report build/reports/public-export-a.json `
  --second-export-report build/reports/public-export-b.json `
  --first-validation-report build/reports/public-validation-a.json `
  --second-validation-report build/reports/public-validation-b.json `
  --expected-database-sha256 DATABASE_SHA256 `
  --expected-source-manifest-sha256 SOURCE_MANIFEST_SHA256 `
  --report build/reports/public-release-audit.json
```

`ready=true`、`failures=[]`、全checkが`true`であることを確認する。

両validation reportの`notice_errors`が空であることを確認する。

chunk超過が1件でもある場合、同じrootを2回指定した場合、A/Bやhashが一致しない場合は合格にしない。

全量exportのread cache、write並列数、validatorの有界並列と再現性ガードは[ADR 0005](decisions/0005-bounded-concurrent-public-build.md)に従う。途中停止した出力にはrelease manifestと完了reportがないため、追記再開や公開候補への流用をしない。

## 5. Workerを検証する

Node.js 22でlockfileから依存を復元し、一括検証を実行する。

```powershell
Set-Location worker
npm ci
npm run verify
```

`verify`はWrangler生成型、typecheck、lint、Vitest、WebMCP bundle、Worker dry-run bundle、npm auditを検査する。

`compatibility_date`はWrangler同梱workerdが対応する最新の検証済み日を使う。カレンダー上の当日へ機械的に進めない。

ローカルR2 fixtureで全route、content negotiation、CORS、404、503、security headerを検査する。

最大groupのCPU時間とR2取得回数を記録する。

既定上限の根拠は[チャンクベンチマーク](verification/chunk-benchmark-2026-08-08.md)に記録する。ローカルwall-clockを本番CPU timeと表現しない。

WebMCPはfeature detection、登録tool数、read-only annotation、同一オリジンAPI呼出し、登録不能時の非破壊動作を検査する。対応ブラウザでの手動smokeを行えない場合は、通常HTML・Markdown・OpenAPIのリリース判定と分けて未検証として記録する。

## 6. リリース監査を記録する

`build/reports/public-release-audit.json`とMarkdown要約を生成する。

全要件の証拠を`docs/requirements-traceability.md`へ反映する。

失敗、未検証、外部状態を明記する。

## 外部公開時に別途行う操作

人が公開候補の差分とcoverageを承認する。

版付き成果物をR2へuploadする。

upload後のhashを再検証する。

Workerの`CURRENT_RELEASE`を変更してdeployする。

本番URLをsmoke testする。

失敗時はWorkerだけを前版へ戻す。

検索index、GPTs、Gem、GPT Actions、Copilot Studioの発見性または互換性は、deploy成功と分けて外部検証する。
