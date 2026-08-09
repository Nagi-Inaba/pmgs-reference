# GitHub公開チェックリスト

このチェックリストは、PMGS Referenceのsource repositoryを公開する前に確認する一般的なrelease gateである。

GitHub repositoryの作成、remote追加、push、visibility変更、release作成はこの文書の実行結果だけでは完了しない。

## 公開対象

公開対象はsource code、schema、合成fixture、設計文書、公開JPO証跡、検証記録である。

次のmaterialは公開対象外である。

- PMGS source package
- source manifestの実データ版
- 生成SQLite
- 全量public export tree
- 登録申込書、credential、連絡先
- confidential patent document
- local absolute pathを含むlogやreport

## 公開履歴

working treeだけでなく、公開するすべてのbranch、tag、到達可能commit、Git objectを検査する。

削除済みfileや旧commitもGitHubから閲覧できるため、現在fileから消えたことだけを合格条件にしない。

過去commitに公開対象外の個人設定、端末固有情報、credential、実データ、不要なworklogが残る場合は、公開前にcleanな公開履歴を用意する。

履歴整理後はcommit author email、tracked path、large blob、secret pattern、source-like fileを再検査する。

公開済み履歴は通常のrelease作業で書き換えない。

## local verification

```powershell
git status --short --branch
git remote -v
git log --format="%H %ae %ce" --all
git rev-list --objects --all
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

次の結果を確認する。

- repository boundary errorが0件である。
- test、typecheck、lint、format、buildがすべて成功する。
- wheelとsdistにsource data、SQLite、archive、credential、local pathがない。
- 10 MiBを超えるGit blobが意図せず存在しない。
- evidence PDFがJPO公開資料だけで、PDF signatureとhashを確認できる。
- synthetic fixture以外のPMGS-shaped source fileがない。
- Markdown linkがrepository内で解決できる。
- 現在の公開表示契約を使う実データA/B auditが完了している。

## repository settings

| 項目 | 推奨値 |
| --- | --- |
| repository name | `pmgs-reference` |
| default branch | `main` |
| license | Apache-2.0 for source code only |
| Issues | enabled |
| Wiki、Projects、Discussions | 必要になるまでdisabled |
| force push | disabled on protected default branch |
| branch deletion | disabled on protected default branch |

description例は次のとおりである。

```text
Versioned Python, MCP, HTML, Markdown, and OpenAPI reference interfaces for registered-use JPO PMGS data.
```

topics例は次のとおりである。

```text
patent-classification pmgs intellectual-property openapi mcp cloudflare-workers
```

## Actionsとsecurity

1. workflowの既定permissionをrepository contentのread-onlyにする。
2. workflowからのpull request作成と承認を不要な場合は許可しない。
3. Dependabot alertとsecurity updateを有効にする。
4. secret scanningとpush protectionを有効にする。
5. private vulnerability reportingを有効にする。
6. CodeQLのPythonとJavaScriptまたはTypeScriptを有効にする。
7. default branchのforce pushとdeletionを禁止する。
8. 初回hosted runで実在するcheck名を確認してからrequired checkへ設定する。

## hosted verification

次のmatrixがGitHub-hosted runnerで成功することを確認する。

- Python 3.12 on Ubuntu
- Python 3.14 on Ubuntu
- Python 3.12 on Windows
- Python 3.14 on Windows
- Cloudflare Worker on Node.js 22

local成功をhosted CI成功と読み替えない。

## visibility変更前の停止条件

- 現在契約の実データA/B auditがない。
- hosted Actionsが未実行または失敗している。
- security設定とbranch ruleを確認できない。
- description、topics、license表示が実装境界と一致しない。
- 実データ、生成DB、local path、credential、公開対象外の運用記録が残る疑いがある。
- READMEのdata取得方法と非同梱方針が実装と一致しない。
- JPO出典、加工表示、非公式サービス表示が公開候補にない。

## GitHub公開後

公開repositoryのcloneを新しいdirectoryへ取得し、repository boundary、test、package contents、linkを再確認する。

R2 upload、Worker deploy、custom domain、PyPI公開はGitHub repositoryの公開とは別のreleaseとして扱う。
