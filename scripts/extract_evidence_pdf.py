"""Extract a public evidence PDF to readable Markdown."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pymupdf


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def extract(source: Path, output: Path, title: str, source_url: str) -> None:
    signature = source.read_bytes()[:5]
    if signature != b"%PDF-":
        raise ValueError(f"not a PDF: {source}")

    document = pymupdf.open(source)
    lines = [
        f"# {title}",
        "",
        f"- 原本URL：{source_url}",
        f"- 原本ファイル：`{source.name}`",
        f"- bytes：{source.stat().st_size}",
        f"- SHA-256：`{sha256(source)}`",
        f"- ページ数：{document.page_count}",
        "- 加工表示：このMarkdownは原本PDFから機械的にテキスト抽出した派生資料です。"
        "正確な内容は原本PDFを確認してください。",
        "",
    ]
    for page_index, page in enumerate(document, start=1):
        extracted = "\n".join(line.rstrip() for line in page.get_text("text").splitlines()).strip()
        lines.extend([f"## ページ{page_index}", "", extracted, ""])
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    extract(args.source, args.output, args.title, args.source_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
