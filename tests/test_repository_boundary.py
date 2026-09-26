from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_repository_boundary.py"


@pytest.fixture
def checker() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT))


@pytest.mark.parametrize("prefix", [b"\0", b"\xff", b"\xff\xfe"])
def test_binary_content_is_not_silently_accepted(
    tmp_path: Path, checker: dict[str, Any], prefix: bytes
) -> None:
    candidate = tmp_path / "notes.txt"
    candidate.write_bytes(prefix + b"internal notes")
    assert checker["content_errors"](candidate, "notes.txt")


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_windows_paths_are_rejected_with_either_separator(
    tmp_path: Path, checker: dict[str, Any], separator: str
) -> None:
    candidate = tmp_path / "notes.txt"
    candidate.write_text(
        "D:" + separator + separator.join(["projects", "private", "note"]), encoding="utf-8"
    )
    assert checker["content_errors"](candidate, "notes.txt") == [
        "notes.txt: local absolute path detected"
    ]


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


@pytest.mark.parametrize(
    "relative",
    [
        "build/report.json",
        "data/export.json",
        "worker/dist/worker.js",
        ".venv/pyvenv.cfg",
        "node_modules/package/index.js",
        "debug.log",
        "backup.sqlite-wal",
        "package.whl",
    ],
)
def test_generated_files_cannot_be_force_added(
    repository: Path, checker: dict[str, Any], relative: str
) -> None:
    candidate = repository / relative
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("{}", encoding="utf-8")
    (repository / ".gitignore").write_text(relative + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "--force", "--", relative], cwd=repository, check=True)
    errors, _ = checker["verify_repository"](repository)
    assert any(error.startswith(relative + ":") for error in errors)


def test_verifier_checks_repository_root_when_invoked_from_a_subdirectory(repository: Path) -> None:
    scripts = repository / "scripts"
    scripts.mkdir()
    copied = scripts / SCRIPT.name
    copied.write_bytes(SCRIPT.read_bytes())
    (repository / "private.txt").write_text("D:" + "/" + "projects/private/note", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(copied)], cwd=scripts, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "private.txt: local absolute path detected" in result.stdout


def test_documented_synthetic_paths_are_only_allowed_in_their_own_tests(
    tmp_path: Path, checker: dict[str, Any]
) -> None:
    candidate = tmp_path / "fixture.txt"
    candidate.write_text("C:" + "/tools/codex.cmd", encoding="utf-8")
    assert checker["content_errors"](candidate, "tests/test_client_detection_security.py") == []
    assert checker["content_errors"](candidate, "notes.txt")


def test_placeholders_are_allowed_and_ignored_local_outputs_are_not_candidates(
    repository: Path, checker: dict[str, Any]
) -> None:
    (repository / ".gitignore").write_text("build/*\n!build/.gitkeep\n", encoding="utf-8")
    (repository / "build").mkdir()
    (repository / "build" / ".gitkeep").touch()
    (repository / "build" / "private.txt").write_bytes(b"\0local only")
    errors, count = checker["verify_repository"](repository)
    assert errors == []
    assert count == 2


def test_links_are_rejected_without_reading_the_target(
    repository: Path, checker: dict[str, Any]
) -> None:
    target = repository.parent / (repository.name + "-outside.txt")
    target.write_text("outside", encoding="utf-8")
    link = repository / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    errors, _ = checker["verify_repository"](repository)
    assert errors == ["linked.txt: linked path must not be published"]
