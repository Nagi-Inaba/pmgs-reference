from __future__ import annotations

import json
import sqlite3
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

import pmgs_reference.agent_kit as agent_kit_module
from pmgs_reference.agent_kit import install_agent_skills, prepare_agent_kit
from pmgs_reference.cli import main
from pmgs_reference.data_paths import write_json_atomic
from pmgs_reference.diagnostics import _sample_identity
from pmgs_reference.store import PMGSStore
from pmgs_reference.validation import validate_database

ROOT = Path(__file__).resolve().parents[1]


def test_agent_kit_generates_distinct_codex_and_claude_configs(
    synthetic_database: Path, tmp_path: Path
) -> None:
    output = tmp_path / "agent-kit"
    result = prepare_agent_kit(
        synthetic_database,
        output,
        python_executable=sys.executable,
        clients=("codex", "claude"),
    )

    codex = tomllib.loads((output / "codex" / "config.toml").read_text(encoding="utf-8"))
    claude = json.loads((output / "claude" / ".mcp.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "agent-kit.json").read_text(encoding="utf-8"))

    assert result.release_id == "JPPM2099001"
    assert codex["mcp_servers"]["pmgs-reference"]["command"] == str(Path(sys.executable))
    assert claude["mcpServers"]["pmgs-reference"]["type"] == "stdio"
    assert manifest["registration_commands"]["codex"][:4] == [
        "codex",
        "mcp",
        "add",
        "pmgs-reference",
    ]
    assert manifest["registration_commands"]["claude"][:4] == [
        "claude",
        "mcp",
        "add",
        "--transport",
    ]
    assert manifest["default_language"] == "ja"
    assert manifest["supported_languages"] == ["ja", "en"]
    assert (output / "skill" / "pmgs-reference" / "SKILL.md").is_file()

    with pytest.raises(FileExistsError):
        prepare_agent_kit(
            synthetic_database,
            output,
            python_executable=sys.executable,
            clients=("codex",),
        )


def test_agent_kit_and_doctor_accept_a_managed_data_directory(
    synthetic_database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_root = tmp_path / "managed"
    validation = validate_database(synthetic_database)
    release = PMGSStore.open(synthetic_database).release_info()
    database = (
        data_root
        / "data"
        / "releases"
        / str(release["release_id"])
        / str(release["source_manifest_sha256"])
        / f"{validation.database_sha256}.sqlite"
    )
    database.parent.mkdir(parents=True)
    database.write_bytes(synthetic_database.read_bytes())
    write_json_atomic(
        data_root / "state" / "current.json",
        {
            "schema_version": "1.0",
            "release_id": release["release_id"],
            "source_manifest_sha256": release["source_manifest_sha256"],
            "database_sha256": validation.database_sha256,
            "database_schema_version": validation.user_version,
            "database_relpath": database.relative_to(data_root).as_posix(),
            "activated_at": "2099-01-01T00:00:00Z",
        },
    )
    output = tmp_path / "agent-kit"

    result = prepare_agent_kit(
        None,
        output,
        python_executable=sys.executable,
        clients=("codex", "claude"),
        data_dir=data_root,
    )

    codex = tomllib.loads((output / "codex" / "config.toml").read_text(encoding="utf-8"))
    claude = json.loads((output / "claude" / ".mcp.json").read_text(encoding="utf-8"))
    assert result.data_dir == data_root.resolve()
    assert codex["mcp_servers"]["pmgs-reference"]["args"][-2:] == [
        "--data-dir",
        str(data_root.resolve()),
    ]
    assert claude["mcpServers"]["pmgs-reference"]["args"][-2:] == [
        "--data-dir",
        str(data_root.resolve()),
    ]
    assert (
        main(
            [
                "doctor",
                "--data-dir",
                str(data_root),
                "--python-executable",
                sys.executable,
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_agent_skill_installer_is_idempotent_but_never_overwrites(tmp_path: Path) -> None:
    first = install_agent_skills(("codex", "claude"), home=tmp_path)
    second = install_agent_skills(("codex", "claude"), home=tmp_path)

    assert {item["status"] for item in first} == {"installed"}
    assert {item["status"] for item in second} == {"already_present"}
    codex_skill = tmp_path / ".agents" / "skills" / "pmgs-reference" / "SKILL.md"
    claude_skill = tmp_path / ".claude" / "skills" / "pmgs-reference" / "SKILL.md"
    assert codex_skill.read_bytes() == claude_skill.read_bytes()

    codex_skill.write_text("different local skill\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        install_agent_skills(("codex",), home=tmp_path)


def test_agent_skill_installer_removes_partial_copy_on_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_incomplete_skill(target: Path) -> None:
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("incomplete\n", encoding="utf-8")

    monkeypatch.setattr(agent_kit_module, "_copy_skill", write_incomplete_skill)
    target = tmp_path / ".agents" / "skills" / "pmgs-reference"

    with pytest.raises(OSError, match="hash mismatch"):
        install_agent_skills(("codex",), home=tmp_path)

    assert not target.exists()


def test_agent_skill_installer_retains_a_concurrent_conflicting_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def create_conflict_then_fail(target: Path) -> None:
        target.mkdir(parents=True)
        (target / "LOCAL.md").write_text("created concurrently\n", encoding="utf-8")
        raise FileExistsError("concurrent skill")

    monkeypatch.setattr(agent_kit_module, "_copy_skill", create_conflict_then_fail)
    target = tmp_path / ".agents" / "skills" / "pmgs-reference"

    with pytest.raises(FileExistsError, match="concurrent skill"):
        install_agent_skills(("codex",), home=tmp_path)

    assert (target / "LOCAL.md").read_text(encoding="utf-8") == "created concurrently\n"


def test_doctor_sample_treats_null_edition_as_unspecified(tmp_path: Path) -> None:
    database = tmp_path / "sample.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE concept (scheme TEXT, normalized_code TEXT, edition TEXT)")
        connection.execute(
            "INSERT INTO concept (scheme, normalized_code, edition) "
            "VALUES ('fi', 'G06F3/048', NULL)"
        )
        connection.commit()
    finally:
        connection.close()

    assert _sample_identity(database)["edition"] is None


def test_agent_skill_contract_and_eval_cases() -> None:
    skill_path = (
        ROOT / "src" / "pmgs_reference" / "resources" / "skills" / "pmgs-reference" / "SKILL.md"
    )
    skill = skill_path.read_text(encoding="utf-8")
    _, frontmatter, body = skill.split("---", maxsplit=2)
    metadata = yaml.safe_load(frontmatter)
    evaluations = json.loads((ROOT / "evals" / "pmgs-agent-evals.json").read_text(encoding="utf-8"))

    assert metadata["name"] == "pmgs-reference"
    assert "TODO" not in skill
    assert "lookup_classification" in body
    assert "not_found" in body
    assert "回答は日本語を既定" in body
    assert "英語" in body
    identifiers = [item["id"] for item in evaluations["cases"]]
    assert len(identifiers) == len(set(identifiers))
    assert all(item["expected"]["must_not_infer"] is True for item in evaluations["cases"])


def test_doctor_cli_checks_real_stdio_and_preserves_database(
    synthetic_database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = synthetic_database.read_bytes()
    result = main(
        [
            "doctor",
            "--db",
            str(synthetic_database),
            "--python-executable",
            sys.executable,
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["ok"] is True
    assert payload["tool_names"] == [
        "lookup_classification",
        "search_pmgs",
        "get_pmgs_document",
    ]
    assert payload["checks"]["database_unchanged"] is True
    assert synthetic_database.read_bytes() == before


def test_agent_kit_cli_and_skill_install_cli(
    synthetic_database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "kit"
    assert (
        main(
            [
                "agent-kit",
                "--db",
                str(synthetic_database),
                "--output",
                str(output),
                "--python-executable",
                sys.executable,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["release_id"] == "JPPM2099001"

    assert (
        main(
            [
                "install-agent-skill",
                "--client",
                "both",
                "--home",
                str(tmp_path / "home"),
            ]
        )
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert {item["client"] for item in installed["skills"]} == {"codex", "claude"}


def test_cli_help_is_japanese_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "PMGS Referenceの構築と読み取り専用照会" in help_text
    assert "特許分類を完全一致で照会する" in help_text
