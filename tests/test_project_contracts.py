from __future__ import annotations

import json
import re
import runpy
import tomllib
from pathlib import Path
from typing import cast
from urllib.parse import unquote

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


def repository_content_errors(path: Path, relative: str) -> list[str]:
    namespace = runpy.run_path(str(ROOT / "scripts" / "verify_repository_boundary.py"))
    checker = cast("object", namespace["content_errors"])
    if not callable(checker):
        raise TypeError("content_errors must be callable")
    result = checker(path, relative)
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise TypeError("content_errors must return list[str]")
    return result


def load_json(relative_path: str) -> object:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_json_schemas_are_valid_draft_2020_12() -> None:
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)


def test_publication_policy_matches_schema() -> None:
    schema = load_json("schemas/publication-policy.schema.json")
    policy = yaml.safe_load((ROOT / "config/publication-policy.yaml").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        policy
    )


def test_normalization_vectors_have_unique_inputs_per_scheme() -> None:
    payload = load_json("schemas/normalization-vectors.json")
    assert isinstance(payload, dict)
    vectors = payload["vectors"]
    keys = [(item["scheme"], item["input"]) for item in vectors]
    assert len(keys) == len(set(keys))


def test_evidence_pdfs_and_extractions_exist() -> None:
    evidence = ROOT / "docs" / "evidence"
    for stem in ["jpo-bulk-download-terms-2026", "jpo-api-handbook-v2.0"]:
        pdf = evidence / f"{stem}.pdf"
        markdown = evidence / f"{stem}.md"
        assert pdf.read_bytes().startswith(b"%PDF-")
        extracted = markdown.read_text(encoding="utf-8")
        assert extracted.startswith("# ")
        assert "機械的にテキスト抽出した派生資料" in extracted
        assert all(line == line.rstrip() for line in extracted.splitlines())


def test_repository_boundary_detects_credentials_and_local_paths(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.txt"
    credential = "gh" + "p_" + ("A" * 20)
    local_path = "D:" + "\\Users\\Actual\\private.txt"
    candidate.write_text(f"{credential}\n{local_path}\n", encoding="utf-8")

    assert set(repository_content_errors(candidate, "candidate.txt")) == {
        "candidate.txt: credential or private-key pattern detected",
        "candidate.txt: local absolute path detected",
    }


def test_repository_boundary_allows_only_documented_path_fixtures(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.txt"
    windows_fixture = "C:" + "\\Users\\Example\\pmgs.sqlite"
    unix_fixture = "/" + "home/example/pmgs.sqlite"
    candidate.write_text(f"{windows_fixture}\n{unix_fixture}\n", encoding="utf-8")

    assert repository_content_errors(candidate, "tests/test_public_export.py") == []


def test_japanese_is_default_and_english_surfaces_are_linked() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    english_readme = (ROOT / "README.en.md").read_text(encoding="utf-8")
    skill = (
        ROOT / "src" / "pmgs_reference" / "resources" / "skills" / "pmgs-reference" / "SKILL.md"
    ).read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "[English](README.en.md)" in readme
    assert "日本語を既定言語" in readme
    assert "[日本語](README.md)" in english_readme
    assert "回答は日本語を既定" in skill
    assert project["project"]["readme"] == "README.md"
    assert "JPO PMGSデータ" in project["project"]["description"]


def test_all_markdown_relative_links_resolve() -> None:
    pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    skipped_directories = {".git", ".venv", "build", "dist", "node_modules"}
    missing: list[str] = []

    for markdown in sorted(ROOT.rglob("*.md")):
        if any(part in skipped_directories for part in markdown.parts):
            continue
        for raw_target in pattern.findall(markdown.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            if path_text and not (markdown.parent / path_text).resolve().exists():
                relative = markdown.relative_to(ROOT).as_posix()
                missing.append(f"{relative} -> {target}")

    assert missing == []
