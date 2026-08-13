# ローカル参照インターフェース

## 目的

正規取得済みPMGS原資料から生成した版付きSQLiteを、Python、CLI、stdio MCP、Codex、Claude Codeから同じ検索契約で参照する。通常の導入は`pmgs setup`がSQLiteの構築、検証、現行版の切替まで行う。

いずれの経路もモデルを呼ばず、定義の要約、分類候補の推測、機械翻訳、ネットワーク取得を行わない。

## データベースの指定

`PMGSStore.open()`とquery系CLIは、次の順でSQLiteを探す。

1. `path`または`--db`で渡した明示パス
2. `data_dir`または`--data-dir`で渡した管理ディレクトリの`state/current.json`
3. `PMGS_REFERENCE_DB`環境変数
4. OS既定の管理ディレクトリにある`state/current.json`
5. pointerがまだない旧構成だけ、管理ディレクトリの`data/current.sqlite`

OS既定の管理ディレクトリはWindowsが`%LOCALAPPDATA%\pmgs-reference`、macOSが`~/Library/Application Support/pmgs-reference`、Linuxが`${XDG_DATA_HOME:-~/.local/share}/pmgs-reference`である。

`current.json`はrelease、source manifest SHA-256、database SHA-256、schema version、管理ディレクトリ内の相対DBパスを持つ。通常のqueryは、形式不正、管理ディレクトリ外への参照、欠損ファイル、内容アドレス付きpathとDB内metadataの不一致をfail closedで拒否し、旧`current.sqlite`へ暗黙にfallbackしない。

実DBの全量SHA-256は参照のたびには計算しない。`pmgs setup`は有効化または再利用前に、`pmgs doctor --data-dir ...`は診断時に、実ファイルhashを`current.json`の`database_sha256`と照合する。内容アドレス付きDBを外部編集した場合は、通常queryの前にこのどちらかを実行する。

PythonパッケージにPMGS原資料やSQLiteは同梱しない。データベースが見つからない場合も自動ダウンロードしない。

照会言語は日本語`ja`を既定とし、原資料に英語がある場合は`en`へ切り替えられる。

## Python API

```python
from pmgs_reference import PMGSStore

store = PMGSStore.open()

record = store.lookup("fi", "G06F3/048", language="ja")
ipc_old = store.lookup("ipc", "G06F3/048", edition="8U", version="2006.01")
classifications = store.search("相互作用技術", schemes=["fi", "ipc"], limit=20)
combined = store.search_pmgs("相互作用技術", limit=20)
parents = store.parents("fi", "G06F3/048")
documents = store.related_documents("ipc", "G06F3/048", edition="8U")
release = store.release_info()
```

公開メソッドは次のとおりである。

- `PMGSStore.open(path=None, *, data_dir=None)`
- `lookup(scheme, code, release="current", edition=None, language="ja", *, version=None, relation_limit=50, relation_offset=0)`
- `search(query, schemes=None, release="current", language="ja", limit=20)`
- `search_pmgs(query, schemes=None, content_types=None, release="current", language="ja", limit=20)`
- `parents(scheme, code, release="current", edition=None)`
- `children(scheme, code, release="current", edition=None)`
- `related_documents(scheme, code, release="current", edition=None)`
- `get_document(document_id, page=None, section=None)`
- `search_documents(query, release="current", language="ja", limit=20)`
- `release_info(release="current")`

IPCで`edition`を省略した場合は、正本に存在する版から`8U`、`8B`、`7`、`7E`、`6`、`5`、`4`の優先順で選ぶ。FIとFタームへ`edition`を渡すと`INVALID_EDITION`になる。`version`はIPCだけに指定でき、CLIでは`--ipc-version`を使う。

IPCのversion省略時はrelease基準日に有効な唯一のrevisionを返す。有効なrevisionがない場合は`not_valid_at_release`、指定したversionがない場合は`version_not_found`を、利用可能なversion一覧とともに正常な構造化応答として返す。旧revisionへ推測でfallbackしない。

分類照会は候補を推測しない。コードが存在しない場合は、空の共通レコードを`match_status: not_found`で返す。入力不正、release不明、文書不明、DBエラーは`PMGSQueryError`の安全な`code`と`message`で区別する。

関係は安定順でページングし、`relation_count`、`relations_truncated`、`next_relation_offset`を返す。`relation_limit`は最大200件である。分類・文書の構造化応答がUTF-8 JSONで4 MiBを超える場合は`RESPONSE_TOO_LARGE`でfail closedにする。

## 文字列検索

3文字以上の各検索語はSQLite FTS5のtrigram索引で照合する。1文字または2文字の検索語を含む場合だけ、エスケープ済み`LIKE`によるリテラル部分一致へ切り替える。

応答の`search_mode`は、使用した経路を次のいずれかで示す。

- `sqlite_fts5_trigram_lexical`
- `sqlite_literal_substring_lexical`
- MCPで分類と文書が異なる経路になった場合の`mixed_lexical`

`search()`は互換性のため分類だけを検索する。`search_pmgs()`は分類と文書を`results_by_type.classification`と`results_by_type.document`へ分け、`limit`を各種類へ独立適用する。いずれも文字列検索であり、意味検索ではない。類義語、表記揺れ、分類候補をAIで補わない。

## 文書応答の上限

`get_document`へ`page`も`section`も指定しない場合、1応答を200節までに制限する。文書全体がそれを超える場合は`segments_truncated: true`と総数を返す。

関連分類も1応答200件までとし、総数と`related_classifications_truncated`を返す。PDFは`page=1`のようにページ単位で取得できる。

## CLI

```powershell
pmgs lookup fi "G06F3/048" --json
pmgs lookup ipc "G06F3/048" --ipc-version 2006.01 --relation-limit 50 --json
pmgs search "相互作用技術" --scheme fi --scheme ipc --json
pmgs search "改正" --content-type document --json
pmgs document DOCUMENT_ID --page 1 --json
pmgs doctor --json
```

`lookup --json`は`not_found`、`version_not_found`、`not_valid_at_release`のいずれも、説明可能な共通recordを出力して終了コード1を返す。該当recordを返した正常照会は0を返す。

`lookup`と`search`の`--language`既定値は`ja`である。英語は`--language en`を指定する。

`doctor`はSQLite schema、release、実stdio接続、tool 3件、read-only annotation、サンプル照会、照会前後hashを検査する。管理ディレクトリを指定した場合は、実ファイルhashと`current.json`の`database_sha256`を照合し、診断中にcurrent pointerが切り替わっていないことも確認する。

## stdio MCP

サーバーは次の読み取り専用toolだけを公開する。

- `lookup_classification`
- `search_pmgs`
- `get_pmgs_document`

起動例：

```powershell
C:\path\to\pmgs-reference\Scripts\python.exe -m pmgs_reference.cli mcp --data-dir C:\path\to\pmgs-data
```

MCPクライアント設定では、裸の`python`、`py`、`uvx`キャッシュではなく、このプロジェクト用の安定仮想環境にある`python.exe`の絶対パスを指定する。

```json
{
  "mcpServers": {
    "pmgs-reference": {
      "command": "C:\\path\\to\\pmgs-reference\\Scripts\\python.exe",
      "args": [
        "-m",
        "pmgs_reference.cli",
        "mcp",
        "--data-dir",
        "C:\\path\\to\\pmgs-data"
      ]
    }
  }
}
```

stdioの標準出力はMCPプロトコル専用とする。診断ログは標準出力へ書かない。

## CodexとClaude Code

```powershell
uv run --frozen pmgs agent-kit `
  --data-dir C:\path\to\pmgs-data `
  --output build\local-agent-kit `
  --python-executable C:\absolute\path\.venv\Scripts\python.exe `
  --client both

uv run --frozen pmgs install-agent-skill --client both
```

通常は`pmgs setup`が登録とskill導入まで行う。`agent-kit`は設定を先にレビューしたい場合に、Codex用TOML、Claude Code用JSON、共通skill、登録commandを新しい出力directoryへ生成する。既存directoryは上書きしない。

`install-agent-skill`は同一内容なら冪等で、内容の異なる同名skillを上書きしない。CodexとClaude Codeの設定形式は別々に保ち、照会手順だけを共通skillとして配布する。

Windowsの一括導入、設定scope、更新、削除は[ローカルAIエージェント導入ガイド](local-agent-kit.md)を参照する。

## 検証

合成fixtureでは、Python API、JSON Schema、CLIの終了コード、MCP tool列挙、構造化応答、入力エラー、実際のstdioクライアント接続、agent kit、skill導入をpytestで検査する。

実データでは、FI、Fターム、IPC 8U、IPC旧版、関連PDFページ、日本語部分語検索、正本ファイルの照会前後ハッシュを検査する。
