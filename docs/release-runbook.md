# 公開候補リリース手順

## 前提

このrunbookは、Web公開候補の検証とPython packageのreleaseを別々の経路として扱う。

第1節から第6節はローカルでWeb公開候補を作り、R2 upload、Worker deploy、ドメイン変更の直前まで検証する。Git操作やWeb deployは含まない。

現在、管理者によるWeb公開は停止中である。第三者が外部公開を行う場合は、本runbookに加えて[Webセルフホストガイド](self-hosting.md)の費用、互換性、upload後全件照合、運用責任を確認する。

## 1. 入力を固定する

原資料を版付きディレクトリとして保持し、旧版を上書きしない。

`pmgs inventory`でbuild前のmanifestとsummaryを生成する。

manifestのファイル件数、bytes、拡張子内訳、論理SHA-256を確認する。

JPO公式ページで一括ダウンロードサービス利用規約の現行URLを確認する。

`config/publication-policy.yaml`のevidence hash、確認日、owner、原典案内URL、加工表示、非公式サービス表示を確認する。

policyのattributionが入力releaseの`COPYRGHT`と完全一致することを確認する。不一致の場合、`export-public`は出力directoryを作る前に拒否する。

v1のsource policyが一つだけであることを確認する。

## 2. 正本を作る

`pmgs build`で一時SQLiteを生成する。

build開始前に、source総bytesの7倍と512 MiBの予備領域を合計した空き容量があることを確認する。空き容量を取得できない場合や不足する場合はbuildを開始しない。

`build_database()`がbuild完了後に同じsourceを再棚卸しし、build前後のファイル件数、bytes、
論理SHA-256が一致することを確認する。不一致なら候補DBをpromoteせず、有効化しない。

build完了後に`user_version=2`、分類record `schema_version=2.0`、`concept`と`concept_revision`の分離、外部キー、FTS、件数、lineage、循環、失敗件数を検査する。

既存の現行DBがschema v1の場合はin-place migrationを行わず、元PMGSからschema v2を再構築する。v1 DBとpointerがv2候補のvalidationと実stdio doctor完了前に変更されず、成功後だけ`current.json`がv2へ切り替わることを確認する。

`document_text_locator_idx`が存在し、`document_id`と`source_locator`の完全一致query planで使用されることも確認する。索引なしのDBは論理的に読めても、全量exportには使用しない。

`pmgs validate DATABASE --report build/reports/validation-report.json`でDBハッシュを含む検査記録を生成する。

検査成功後だけ指定先へ原子的に置き換える。

## 3. ローカル参照面を検証する

`ruff check .`、`mypy`、`pytest`を実行する。

実データでFI、Fターム、IPC 8U、IPC旧版、`reference_only` FI、階層、関連文書、PDFページ、日本語部分語検索を照合する。IPCはrelease基準日によるversion省略照会と明示version照会を分け、有効revisionがない場合に旧版へfallbackしないことを確認する。

関係は`relation_limit`と`relation_offset`で複数ページを取得し、`relation_count`、`relations_truncated`、`next_relation_offset`と重複や欠落がないことを確認する。`search_pmgs`は分類と文書の両方を要求し、`results_by_type`の二群と種類ごとの上限を確認する。

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

同じcodeの全revisionが一つの分類bundleに収まり、bundleがJSON chunkをまたがないことを確認する。単一分類bundleの上限は常に256 KiBであり、`--max-json-chunk-bytes`は文書を含むchunk設定として維持する。chunk設定を256 KiBより大きくしても分類bundleが256 KiBを超えれば失敗しなければならない。

元ファイル、SQLite、一括JSON、ローカル絶対パス、ユーザー名、秘密情報が含まれないことを検査する。

公開候補root、その祖先、子directory、各objectにsymbolic link、junction、reparse point、hard linkが
ないことを検査し、読込中にfile identityが変わった場合も拒否する。HTMLはmeta refresh、埋込みobject、
protocol-relative URL、自動外部resource、外部form action、外部CSS URLを拒否する。

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

## Pythonパッケージのリリース

Python packageはWeb公開候補と独立してreleaseできる。`release.yml`はtag付きsourceを再検証し、一度buildしたwheelとsdistをartifactとして固定する。PyPI公開後、その同じartifactからGitHub Releaseを作る。

### 1. ローカル候補を検証する

```powershell
uv lock --check
uv run --frozen python scripts/verify_repository_boundary.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest -q
uv build
npm --prefix worker ci
npm --prefix worker run verify
```

wheelを隔離されたtool環境へ導入し、source checkoutに依存せず`pmgs setup`、同一sourceの再実行、`pmgs doctor`、分類lookup、stdio MCPの3 tool、version表示が成功することも確認する。

```powershell
uv build --wheel
uv run --frozen python scripts/verify_wheel_install.py `
  --dist-dir dist `
  --source tests/fixtures/synthetic_pmgs
```

検証scriptは`pyproject.toml`のversionと一致するwheelだけを選ぶ。`dist/`に過去versionのwheelが残っていても対象に含めず、現行versionのwheelが0件または複数件なら停止する。

隔離wheelと検証済みschema v2 DBを使い、CodexとClaude Codeを別々に実参照評価する。
Codexは評価専用`CODEX_HOME`から起動し、既存の認証fileだけを一時homeへ分離コピーする。
元の認証fileを変更せず、認証内容をreportへ保存せず、評価終了時に一時homeを破棄する。
`--source`は追跡済み合成fixtureのmanifest SHA-256と完全一致する場合だけ許可し、
リンク、改変fixture、コピー前後の差を外部clientの起動前に拒否する。
評価用MCP設定と配布skillだけを読み込み、永続session、ブラウザ、shellなどPMGS以外のtoolを
無効化し、環境変数をallowlistへ限定する。FI、Fターム、IPCの基準日選択と明示version、
`reference_only`、分類と文書の検索、関係ページング、該当なし、prompt injectionを検査し、
禁止tool呼出しが0件であることを確認する。認証失敗や片方のclient未検証を、
もう片方の成功で補完しない。

### 2. 外部設定を確認する

GitHubに`pypi` environmentを作り、required reviewerと`v*` tagだけを許可するdeployment ruleを設定する。

PyPIのpending Trusted Publisherは次の値を使う。

| 項目 | 値 |
| --- | --- |
| PyPI project | `pmgs-reference` |
| GitHub owner | `Nagi-Inaba` |
| repository | `pmgs-reference` |
| workflow | `release.yml` |
| environment | `pypi` |

PyPI上のproject名が利用可能か、既存projectを正しく管理できることをrelease直前に確認する。取得できない場合は自動で別名へ変更せず、package名とrepository契約を改めて判断する。

workflowはPyPI publish jobだけへ`id-token: write`を与える。API tokenをrepository secretへ保存しない。Trusted Publishingの設定とenvironment利用は[PyPI公式手順](https://docs.pypi.org/trusted-publishers/using-a-publisher/)、provenance attestationは[PyPI公式attestation手順](https://docs.pypi.org/attestations/producing-attestations/)を基準にする。

### 3. versionとtagを一致させる

`pyproject.toml`のversion、README、状態記録を更新し、次のguardを通す。

```powershell
uv run --frozen python scripts/verify_release_tag.py --tag v0.4.0
```

検証済みcommitへ`v<version>` tagを作ってpushする。この外部操作は、差分review、mainのhosted CI、公開承認が完了した場合だけ行う。

### 4. workflow結果を確認する

`build` jobがboundary、Ruff、format、mypy、pytest、wheel、sdistを再検証した後、`publish-pypi` jobは`pypi` environmentで承認待ちになる。

承認後、PyPI Trusted Publishingとattestation付きで配布する。PyPI成功後だけ`publish-github` jobが同じwheelとsdistからGitHub Releaseを作る。

### 5. 公開物を外部検証する

PyPI project page、version、hash、attestation、GitHub Releaseのassetを確認する。空の環境から`uv tool install pmgs-reference`を実行し、`pmgs --version`と合成fixtureの`pmgs setup`をsmoke testする。

GitHub Releaseだけ成功、PyPIだけ成功、workflowが承認待ちなどの部分状態を区別して`docs/current-status.md`へ記録する。
