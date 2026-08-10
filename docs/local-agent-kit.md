# Codex・Claude Code向けローカル導入

[English](local-agent-kit.en.md)

## 利用できる範囲

ローカル導入は、利用者が正規に取得したPMGS packageからSQLiteを生成し、CodexまたはClaude Codeへ読み取り専用stdio MCPとして接続する。

AIエージェントが利用するtoolは次の3個に限る。

- `lookup_classification`
- `search_pmgs`
- `get_pmgs_document`

配布スキルは日本語回答を既定とし、利用者が英語を指定した場合は`language: en`へ切り替える。公式文言、AIによる説明、該当なしを混同せず、分類を推測しない。

## Windowsの一括セットアップ

リポジトリのrootで実行する。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both
```

スクリプトは次の順で処理する。

1. `uv sync --frozen --all-groups`でリポジトリ固有の仮想環境を準備する。
2. `.venv\Scripts\python.exe`の署名と`.venv\pyvenv.cfg`を確認する。
3. PMGS原資料を棚卸しし、SQLiteを新規生成して検証する。
4. 実際のstdio MCP clientで初期化、tool列挙、サンプル照会を行う。
5. 照会前後のSQLite SHA-256が一致することを確認する。
6. Codex用TOML、Claude Code用JSON、共通スキル、登録commandを`build/local-agent-kit/`へ生成する。
7. 共通スキルを個人用skill directoryへ導入する。

既存のSQLite、agent kit、内容の異なる同名スキルは上書きしない。既定ではCodex・Claude CodeのMCP設定も変更しない。

## 生成物

```text
build/local-agent-kit/
├── agent-kit.json
├── codex/config.toml
├── claude/.mcp.json
└── skill/pmgs-reference/
    ├── SKILL.md
    └── agents/openai.yaml
```

`agent-kit.json`には、解決済みのPython、SQLite、リリース、対象client、skill hash、登録commandが入る。ローカル絶対パスを含むためGitへ追加しない。

## MCPを登録する

セットアップ時に登録まで行う場合は`-RegisterClients`を追加する。このflagはclient設定を変更するため、利用者が明示的に選ぶ。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local_agent.ps1 `
  -SourceDirectory C:\path\to\JPPM2026002 `
  -ReleaseId JPPM2026002 `
  -Client both `
  -RegisterClients
```

手動登録では、`agent-kit.json`の`registration_commands`を確認して使う。commandの形は次のとおりである。

```powershell
codex mcp add pmgs-reference -- C:\absolute\path\.venv\Scripts\python.exe -m pmgs_reference.cli mcp --db C:\absolute\path\current.sqlite

claude mcp add --transport stdio --scope user pmgs-reference -- C:\absolute\path\.venv\Scripts\python.exe -m pmgs_reference.cli mcp --db C:\absolute\path\current.sqlite
```

Codexは個人用`~/.codex/config.toml`または信頼済みprojectの`.codex/config.toml`を使う。Claude Codeのproject scopeはrepository rootの`.mcp.json`、user scopeは`~/.claude.json`を使う。PMGSの絶対パスを共有repositoryへ入れないため、個人利用ではuser scopeを推奨する。

現行のクライアント仕様は、[Codex MCP](https://developers.openai.com/codex/mcp)と[Claude Code MCP](https://code.claude.com/docs/en/mcp)で確認する。

## スキルを導入する

セットアップスクリプトを使わない場合は、次のcommandだけでも導入できる。

```powershell
uv run --frozen pmgs install-agent-skill --client both
```

個人用の導入先は次のとおりである。

| Client | 導入先 |
| --- | --- |
| Codex | `~/.agents/skills/pmgs-reference/` |
| Claude Code | `~/.claude/skills/pmgs-reference/` |

CodexとClaude Codeで同じ`SKILL.md`を使う。client固有の設定形式を無理に共通化しない。

スキルの現行仕様は[OpenAIのSkills](https://learn.chatgpt.com/docs/build-skills)と[Claude CodeのSkills](https://code.claude.com/docs/en/skills)を参照する。

## 手動でagent kitを作る

Windows以外、またはSQLiteをすでに生成済みの場合は、次のcommandを個別に実行する。

```powershell
uv sync --frozen --all-groups
uv run --frozen pmgs validate C:\path\to\current.sqlite
uv run --frozen pmgs doctor --db C:\path\to\current.sqlite --json
uv run --frozen pmgs agent-kit `
  --db C:\path\to\current.sqlite `
  --output build\local-agent-kit `
  --python-executable C:\absolute\path\.venv\Scripts\python.exe `
  --client both
uv run --frozen pmgs install-agent-skill --client both
```

LinuxとmacOSでは、`python_executable`へそのリポジトリの`.venv/bin/python`の絶対パスを渡す。

## 動作確認

```powershell
uv run --frozen pmgs doctor --db C:\path\to\current.sqlite --json
codex mcp list
claude mcp list
```

`doctor`の成功条件は次のとおりである。

- SQLite schemaとrelease metadataが有効である。
- server identityが`pmgs-reference`である。
- 3個のtoolが契約どおりの順序で公開される。
- すべてのtoolがread-onlyかつnon-destructiveである。
- 実stdio経由のサンプル照会が一致する。
- SQLiteの照会前後SHA-256が一致する。

クライアント側では、次のような依頼で試す。

```text
$pmgs-reference を使って、FI G06F3/048の公式定義、階層、出典、PMGSリリースを確認してください。
```

英語では次のように指定する。

```text
Use $pmgs-reference and answer in English. Look up FI G06F3/048 and cite the PMGS release and source.
```

## 更新と削除

SQLiteを更新するときは、既存DBへ上書きせず新しいfileへbuild・validate・doctorを行う。検証後にMCP設定の`--db`を切り替え、旧DBは必要な期間だけ保持する。

配布スキルのinstallerは同じ内容なら冪等で、内容が違う同名directoryは上書きしない。更新時は現行と新しいスキルの差分を確認してから、利用者が旧directoryを削除して再導入する。

MCP登録を外す場合は、次のclient commandを使う。

```powershell
codex mcp remove pmgs-reference
claude mcp remove pmgs-reference
```

その後、不要になった個人用skill directoryとローカルDBを、正確なpathを確認してから利用者が削除する。

## 失敗時の確認箇所

| 症状 | 確認箇所 |
| --- | --- |
| `database not found` | MCP設定の`--db`が絶対パスか、fileが存在するか |
| clientからserverが見えない | `codex mcp list`または`claude mcp list`、client再起動 |
| stdio protocol error | commandがログを標準出力へ出していないか |
| skillが起動しない | 導入先、`SKILL.md` frontmatter、clientのskill一覧 |
| IPCの結果が違う | `edition`を明示し、返された版を確認したか |
| 定義が見つからない | schemeとcodeを確認し、`not_found`を推測で補っていないか |

PMGS原資料、SQLite、`agent-kit.json`をIssue、Pull Request、公開ログへ貼り付けない。
