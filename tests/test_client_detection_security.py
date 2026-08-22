from __future__ import annotations

import os
from pathlib import Path

import pytest

from pmgs_reference.client_integration import detect_client_targets


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
