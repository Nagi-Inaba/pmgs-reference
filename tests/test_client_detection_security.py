from __future__ import annotations

import os
from pathlib import Path

import pytest

from pmgs_reference.client_integration import SubprocessCommandRunner, detect_client_targets


@pytest.mark.skipif(os.name != "nt", reason="Windows command lookup behavior")
def test_auto_detection_rejects_tilde_relative_path_before_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles = tmp_path / "profiles"
    victim_profile = profiles / "victim"
    attacker_bin = profiles / "attacker" / "bin"
    victim_profile.mkdir(parents=True)
    attacker_bin.mkdir(parents=True)
    (attacker_bin / "codex.cmd").write_text("@exit /b 0\n", encoding="utf-8")

    monkeypatch.setenv("USERPROFILE", str(victim_profile))
    monkeypatch.setenv("USERNAME", "victim")
    monkeypatch.setenv("PATH", r"~attacker\bin")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")

    targets = detect_client_targets("auto")

    assert targets == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch lookup behavior")
def test_batch_launcher_does_not_resolve_helpers_from_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_bin = tmp_path / "trusted-bin"
    untrusted_working_directory = tmp_path / "untrusted-working-directory"
    trusted_bin.mkdir()
    untrusted_working_directory.mkdir()

    launcher = trusted_bin / "codex.cmd"
    launcher.write_text("@echo off\r\nhelper\r\nexit /b %errorlevel%\r\n", encoding="utf-8")
    (trusted_bin / "helper.cmd").write_text(
        '@echo trusted>"%TRUSTED_MARKER%"\r\n@exit /b 0\r\n',
        encoding="utf-8",
    )
    (untrusted_working_directory / "helper.cmd").write_text(
        '@echo malicious>"%MALICIOUS_MARKER%"\r\n@exit /b 0\r\n',
        encoding="utf-8",
    )

    trusted_marker = tmp_path / "trusted.txt"
    malicious_marker = tmp_path / "malicious.txt"
    monkeypatch.chdir(untrusted_working_directory)
    monkeypatch.setenv("PATH", str(trusted_bin))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setenv("TRUSTED_MARKER", str(trusted_marker))
    monkeypatch.setenv("MALICIOUS_MARKER", str(malicious_marker))
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)

    result = SubprocessCommandRunner().run(launcher, ())

    assert result.returncode == 0
    assert trusted_marker.is_file()
    assert not malicious_marker.exists()
