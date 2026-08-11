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

`current.json`はrelease、source manifest SHA-256、database SHA-256、schema version、管理ディレクトリ内の相対DBパスを持つ。形式不正、管理ディレクトリ外への参照、欠損ファイル、DBとのidentity不一致はfail closedで拒否し、旧`current.sqlite`へ暗黙にfallbackしない。

PythonパッケージにPMGS原資料やSQLiteは同梱しない。データベースが見つからない場合も自動ダウンロードしない。

照会言語は日本語`ja`を既定とし、原資料に英語がある場合は`en`へ切り替えられる。

## Python API

```python
from pmgs_reference import PMGSStore

store = PMGSStore.open()

record = store.lookup("fi", "G06F3/048", language="ja")
results = store.search("相互作用技術", schemes=["fi", "ipc"], limit=20)
parents = store.parents("fi", "G06F3/048")
documents = store.related_documents("ipc", "G06F3/048", edition="8U")
release = store.release_info()
```

公開メソッドは次のとおりである。

- `PMGSStore.open(path=None, *, data_dir=None)`
- `lookup(scheme, code, release="current", edition=None, language="ja")`
- `search(query, schemes=None, release="current", language="ja", limit=20)`
- `parents(scheme, code, release="current", edition=None)`
- `children(scheme, code, release="current", edition=None)`
- `related_documents(scheme, code, release="current", edition=None)`
- `get_document(document_id, page=None, section=None)`
- `search_documents(query, release="current", language="ja", limit=20)`
- `release_info(release="current")`

IPCで`edition`を省略した場合は、正本に存在する版から`8U`、`8B`、`7`、`7E`、`6`、`5`、`4`の優先順で選ぶ。FIとFタームへ`edition`を渡すと`INVALID_EDITION`になる。

分類照会は候補を推測しない。コードが存在しない場合は、空の共通レコードを`match_status: not_found`で返す。入力不正、release不明、IPC版不明、文書不明は、`PMGSQueryError`の安全な`code`と`message`で区別する。

## 文字列検索

3文字以上の各検索語はSQLite FTS5のtrigram索引で照合する。1文字または2文字の検索語を含む場合だけ、エスケープ済み`LIKE`によるリテラル部分一致へ切り替える。

応答の`search_mode`は、使用した経路を次のいずれかで示す。

- `sqlite_fts5_trigram_lexical`
- `sqlite_literal_substring_lexical`
- MCPで分類と文書が異なる経路になった場合の`mixed_lexical`

いずれも文字列検索であり、意味検索ではない。類義語、表記揺れ、分類候補をAIで補わない。

## 文書応答の上限

`get_document`へ`page`も`section`も指定しない場合、1応答を200節までに制限する。文書全体がそれを超える場合は`segments_truncated: true`と総数を返す。

関連分類も1応答200件までとし、総数と`related_classifications_truncated`を返す。PDFは`page=1`のようにページ単位で取得できる。

## CLI

```powershell
pmgs lookup fi "G06F3/048" --json
pmgs search "相互作用技術" --scheme fi --scheme ipc --json
pmgs search "改正" --content-type document --json
pmgs document DOCUMENT_ID --page 1 --json
pmgs doctor --json
```

`lookup --json`は該当なしの共通レコードを出力して終了コード1を返す。正常照会は0を返す。

`lookup`と`search`の`--language`既定値は`ja`である。英語は`--language en`を指定する。

`doctor`はSQLite schema、release、実stdio接続、tool 3件、read-only annotation、サンプル照会、照会前後hashを検査する。

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
