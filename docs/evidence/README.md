# 公開証跡

このディレクトリは、JPOが一般公開している規約と技術資料の原本PDF、および検索可能な抽出Markdownを保存する。

## 収録資料

| basename | 位置付け |
| --- | --- |
| `jpo-bulk-download-terms-2026` | 一括ダウンロードサービスの利用規約 |
| `jpo-api-handbook-v2.0` | 2026-08-09確認時点の現行API手引き |
| `jpo-api-handbook-v1.4` | 改訂前API手引きの履歴資料 |

各basenameには原本`.pdf`と抽出`.md`がある。

## 加工表示

Markdownは`scripts/extract_evidence_pdf.py`で原本PDFから機械的にテキスト抽出した派生資料である。

抽出結果には改行、文字認識、箇条書き、表の順序が原本と異なる場合がある。

正確な内容、図表、版表示は原本PDFを優先する。

各Markdownの先頭に原本URL、原本file、bytes、SHA-256、page数、加工表示を記録する。

## 利用条件

JPOウェブサイトの一般的なコンテンツ利用条件は、出典表示と加工表示を求めている。

一括ダウンロードデータ自体の提供境界は、保存した一括ダウンロードサービス利用規約と`config/publication-policy.yaml`で別に管理する。

repositoryのApache-2.0 licenseは、このディレクトリのJPO資料を再licenseしない。

登録申込書、ID、password、連絡先、登録証明は保存しない。

資料の位置付け、URL、bytes、SHA-256は[登録条件と公開形態](../registered-use-terms.md)に記録する。
