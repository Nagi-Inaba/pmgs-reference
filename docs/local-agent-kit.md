# Codex・Claude Codeへの導入

## まず使い始める

必要なのは、利用登録後に取得したPMGSパッケージと[uv](https://docs.astral.sh/uv/)です。

PyPIでv0.3.0が公開された後は、次のように導入できます。

```powershell
uv tool install pmgs-reference
pmgs setup C:\path\to\JPPM2026002
```

GitHubのソースから試す場合は、リポジトリで`uv tool install .`を実行してから同じ`pmgs setup`を使います。

セットアップは次の順に進みます。

1. PMGSパッケージを棚卸しし、全ファイルの論理SHA-256を固定する。
2. 検証済みの同一SQLiteがあれば再利用し、なければ新しく構築する。
3. 構築中に原資料が変わっていないことを再確認する。
4. SQLiteの構造と内容を検証し、実際のstdio MCP接続を診断する。
5. 合格したSQLiteだけを現行版へ切り替える。
6. 選択したCodex・Claude CodeへMCPと共通スキルを登録する。

CodexまたはClaude Codeが見つかると、次のように確認します。Enterだけで登録します。

```text
codexにPMGS Referenceを登録しますか? [Y/n]
```

セットアップ後、新しいAIセッションで次のように依頼できます。

```text
$pmgs-reference を使って、FI G06F3/048の定義、階層、版、出典を確認して。
```

## クライアントを指定する

`--client auto`が既定で、端末にあるCodexとClaude Codeを検出します。対象や登録動作を固定したい場合は明示します。

```powershell
pmgs setup C:\path\to\JPPM2026002 --client codex --register
pmgs setup C:\path\to\JPPM2026002 --client claude --register
pmgs setup C:\path\to\JPPM2026002 --client both --register
pmgs setup C:\path\to\JPPM2026002 --client none --no-register
```

既に同じ接続とスキルがある場合はそのまま再利用します。同名で内容が異なる設定やスキルは上書きせず、結果を`conflict`として返します。

Claude Codeで`CLAUDE_CONFIG_DIR`を設定している場合は、そのカスタムプロファイル内のMCP設定と`skills/pmgs-reference`を確認・更新します。

## PMGSの版を更新する

新しいPMGSパッケージを同じように指定します。

```powershell
pmgs setup C:\path\to\JPPM2027001
```

新しいSQLiteは旧版と別の場所へ作られます。検証とMCP診断が完了した時点で`current.json`だけを原子的に切り替えるため、途中で失敗してもそれまでの現行版は変わりません。旧版のSQLiteは自動削除しません。

MCP設定は管理ディレクトリを参照するので、更新ごとの再登録は不要です。現行版を切り替えた後は、実行中のCodexまたはClaude Codeセッションを再起動してください。

## 保存先

既定の管理ディレクトリはOSごとに次の場所です。

| OS | 保存先 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\pmgs-reference` |
| macOS | `~/Library/Application Support/pmgs-reference` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/pmgs-reference` |

主なファイルは次の構成になります。

```text
pmgs-reference/
├── state/current.json
├── data/releases/<release>/<source-sha256>/<database-sha256>.sqlite
├── reports/<setup-run>/
└── staging/
```

別の保存先を使う場合は`--data-dir`を指定します。

```powershell
pmgs setup C:\path\to\JPPM2026002 --data-dir C:\path\to\pmgs-data
pmgs doctor --data-dir C:\path\to\pmgs-data --json
```

Pythonでは`PMGSStore.open(data_dir=...)`、CLIでは`--data-dir`で同じ現行版を参照できます。

## 自動実行とJSON結果

非対話実行では、登録するかどうかを必ず明示します。

```powershell
pmgs setup C:\path\to\JPPM2026002 `
  --client both `
  --register `
  --non-interactive `
  --json
```

ローカルDBだけを準備する場合は`--client none --no-register`を使います。`--dry-run`を加えると入力の解決と棚卸しだけを行い、保存先やクライアント設定を変更しません。

終了コードは、完了または再利用が`0`、構築・診断・登録の失敗が`1`、引数の誤りが`2`です。JSONモードは標準出力へ結果オブジェクトを1件だけ出し、進捗は標準エラーへ出します。

## 診断する

```powershell
pmgs doctor --json
codex mcp list
claude mcp list
```

`doctor`はSQLiteのschemaとrelease、MCP tool 3件、読み取り専用annotation、実stdio照会、照会前後のSQLiteハッシュを検査します。管理ディレクトリを使う場合は、実ファイルのSHA-256が`current.json`の値と一致し、診断中に現在版が切り替わっていないことも確認します。通常のlookupは大きなDBを毎回全量hashしないため、DBを外部編集した場合や破損が疑われる場合は先に`doctor`を実行してください。

## リポジトリから実行する場合

Windows用スクリプトは`pmgs setup`へ引数を渡す薄いラッパーです。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -Client codex `
  -RegisterClients
```

Windows以外では`uv run --frozen pmgs setup ...`を直接実行できます。

## 接続を外す

MCP登録だけを外す場合は、各クライアントのコマンドを使います。

```powershell
codex mcp remove pmgs-reference
claude mcp remove pmgs-reference
```

SQLiteや旧版を削除する場合は、`state/current.json`が参照している現行ファイルを確認してから、不要な版だけを明示的に削除します。
