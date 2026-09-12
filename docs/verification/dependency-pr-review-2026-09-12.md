# 依存関係PRのレビューと検証（2026-09-12）

## 対象と判断

| PR | レビュー結果 |
| --- | --- |
| [#68](https://github.com/Nagi-Inaba/pmgs-reference/pull/68) | setup-uv 10.0.1の公式tagと固定SHAの一致、差分が11箇所のaction参照だけであること、必須CI成功を確認し、`1752da8`へsquash mergeした。 |
| [#69](https://github.com/Nagi-Inaba/pmgs-reference/pull/69) | Worker依存6件の更新。WebMCPテストの型エラー5件とsharpの脆弱性を修正対象とした。 |
| [#76](https://github.com/Nagi-Inaba/pmgs-reference/pull/76) | httpx2とhttpcore2を2.12.0へ同時更新する。追加のhttpx2-jsfetchはEmscriptenだけに適用される。Pythonのローカル検査に合格した。 |
| [#77](https://github.com/Nagi-Inaba/pmgs-reference/pull/77)、[#78](https://github.com/Nagi-Inaba/pmgs-reference/pull/78) | 両PRの差分は同一。Vitest 4.1.11への更新は#69にも含まれる。 |
| [#79](https://github.com/Nagi-Inaba/pmgs-reference/pull/79) | httpcore2とhttpx2を2.10.0へ更新する。#76の2.12.0更新が含む範囲と重なる。 |

## Workerの修正とローカル検証

- `webmcp-types` 0.1.5の`execute(input, options)`に合わせ、既存テスト5箇所へ`AbortSignal`を渡した。アサーションは維持した。
- [sharpの脆弱性情報](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c)に対応し、`overrides`でsharpを0.35.4に固定した。二つのMiniflare依存経路が同じ修正版を参照することを`npm ls sharp --all`で確認した。
- `npm audit --package-lock-only --json`と導入後の`npm audit --audit-level=high`は脆弱性0件だった。監査の実行条件は変更していない。
- `types:check`、TypeScript型検査、oxlint、WebMCPテスト3件、WebMCP生成、Worker dry-run bundleに合格した。生成済みWebMCPとWorker bindingには差分がない。
- Worker全体テストはWindowsでrunner起動が90秒後にtimeoutし、テスト実行0件、エラー2件となった。終了後の`npm ci`はworkerd実行ファイルの`EPERM`で失敗した。`npm install --ignore-scripts`で依存を復元して上記の個別検査を実行した。Worker全体のローカル合格は主張しない。
- JSON parser、`git diff --check`、repository-boundary verifierに合格した。
- 独立セキュリティレビューは`PASS`、重大指摘0件だった。sharpの全解決経路、27個のlock更新エントリ、監査の維持、WebMCPテストの非弱化を確認した。変更したMarkdownのローカルリンク8件も解決した。

## Pythonのローカル検証

対象は#76のcommit `397321d707d0e72754ebc7252de0ee0520ea05bd`。署名を確認したCPython 3.14.3で分離環境を作成し、`pyvenv.cfg`の参照先も確認した。

`uv lock --check`、repository-boundary verifier、Ruff、format、mypy、`uv build`に合格した。`pytest -q`は345件合格、9件skip、83.73秒だった。skipはWindowsのsymlink権限とPOSIX限定挙動による。

## 外部検証の状態

#68統合後の[main CI](https://github.com/Nagi-Inaba/pmgs-reference/actions/runs/34674146285)は、16 job中15 jobが成功し、Worker jobは既存sharpの脆弱性監査で失敗した。修正後のPRと統合後mainについて、最新commitの必須CI成功をマージ判断の条件とする。

この記録は依存更新の検証であり、PyPI公開、GitHub Release作成、R2 upload、Worker deployを実施した記録ではない。
