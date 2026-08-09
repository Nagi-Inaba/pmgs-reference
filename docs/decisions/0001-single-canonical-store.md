# ADR 0001：一つのSQLite正本から全インターフェースを生成する

- 状態：採用
- 日付：2026-08-08

## 背景

ローカルPython、CLI、MCP、ウェブ、JSON APIが別々にPMGS形式を解釈すると、正規化、版、本文、出典がずれる。

公開Workerで約1 GBの原資料を解析する構成は、CPU制限と再現性の両方に適さない。

## 決定

Python ingestionが版付きSQLite正本を生成する。

ローカルAPIはSQLiteを直接読む。

公開HTML、Markdown、JSON、manifestは同じSQLiteから決定的に生成する。

Workerは公開成果物だけを読む。

## 帰結

分類コードの正規化と出典追跡を一か所で検証できる。

公開buildはSQLiteを配布せず、recordまたはdocument単位の成果物を生成する必要がある。

schema変更時はPython API、export、Worker契約の互換性を同じreleaseで検査する必要がある。
