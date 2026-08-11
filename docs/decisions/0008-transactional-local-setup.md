# ADR 0008: `pmgs setup`でローカル正本をトランザクション管理する

- 状態: 採用
- 日付: 2026-08-11

## 文脈

従来のローカル導入は、inventory、build、validate、doctor、agent kit生成、skill導入、client登録を個別に実行する必要があった。Windows用スクリプトはこの手順をまとめていたが、既存DBを再利用できず、macOSとLinuxの利用者、PyPIから導入する利用者には同じ入口を提供できなかった。

PMGSのSQLiteは大きいため、毎回の再構築、現行DBの上書き、更新途中の切替失敗を避ける必要がある。CodexとClaude Codeの設定をPMGSの版ごとに書き換える運用も更新ミスにつながる。

## 決定

Python CLIの`pmgs setup SOURCE`を、全OSと全インストール形態に共通するローカル導入口とする。

セットアップは次の契約に従う。

1. sourceは`JPPM`と数字からなる版ディレクトリ、明示した`--release`、または親直下の一意な版ディレクトリから解決する。曖昧な版、版の不一致、symlinkまたはjunctionを含むsourceは拒否する。
2. source inventoryを構築前後に生成し、論理SHA-256が一致しない候補を有効化しない。
3. SQLiteは`data/releases/<release>/<source-sha256>/<database-sha256>.sqlite`へ内容アドレス付きで保存し、既存ファイルを上書きしない。
4. schema検証と実stdio MCP診断に合格したSQLiteだけを`state/current.json`から参照する。
5. `current.json`は管理ディレクトリ内の相対パスとidentityを持ち、同一ディレクトリの一時ファイルから原子的に置き換える。
6. setup lockは同じ管理ディレクトリへの同時実行を一つに制限する。所有を確認できるstagingだけを回収し、旧版SQLiteは自動削除しない。
7. MCP登録は個別DBではなく`--data-dir`を使う。既存の同名設定またはskillが異なる場合は上書きしない。
8. 対話実行は検出したclientごとに`[Y/n]`で登録を確認する。JSONまたは非対話実行は`--register`か`--no-register`を必須にする。
9. `--dry-run`はsource解決、棚卸し、予定したclient処理の表示だけを行い、管理ディレクトリやclient設定を変更しない。

OS既定の管理ディレクトリは、Windowsが`%LOCALAPPDATA%\pmgs-reference`、macOSが`~/Library/Application Support/pmgs-reference`、Linuxが`${XDG_DATA_HOME:-~/.local/share}/pmgs-reference`とする。

旧構成の`data/current.sqlite`は、`current.json`が存在しない場合だけ読み取る。releaseとsource hashが要求と一致すれば移動や削除をせずに現行版としてpointerを作成し、一致しなければ保持して新しい候補を構築する。

## 結果

利用者は、インストール方法やOSにかかわらず`pmgs setup`だけでSQLiteの構築、検証、切替、AI client接続まで実行できる。

同じsourceは検証済みDBを再利用する。新しいPMGSへ更新してもclient設定は変わらず、失敗した候補が現行版になることもない。

内容アドレス付きDBと旧版保持によりディスク使用量は増える。削除は将来の明示的な管理コマンドまたは利用者の確認済み操作で扱い、自動cleanupは導入しない。

ファイル置換の原子性は各OSの同一filesystem内のrename契約に依存する。電源断まで含む永続性は、通常の単体testだけでは完全には証明しない。

## 不採用案

PowerShellスクリプトを正本にする案は、macOS、Linux、wheel導入で同じ動作を再利用できないため採用しない。

`current.sqlite`を上書きする案は、更新失敗時の回復と旧版保持が難しくなるため採用しない。

各client設定へ内容アドレス付きDBの絶対パスを書く案は、PMGS更新ごとに設定変更が必要になるため採用しない。
