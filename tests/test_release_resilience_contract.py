from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_publish_waits_for_three_os_verification() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    publish_needs = jobs["publish-pypi"]["needs"]
    required = set(publish_needs if isinstance(publish_needs, list) else [publish_needs])

    assert {
        "verify-linux",
        "verify-windows",
        "verify-macos",
        "compare-synthetic-determinism",
        "verify-distributions",
    } <= required


def test_sdist_is_built_and_installed_in_isolation_before_publish() -> None:
    workflow_text = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    verifier = ROOT / "scripts" / "verify_sdist_install.py"

    assert verifier.is_file()
    assert "verify_sdist_install.py" in workflow_text
    assert "verify_wheel_install.py" in workflow_text
    assert "publish-pypi" in workflow_text
    assert workflow_text.index("verify_sdist_install.py") < workflow_text.index(
        "Publish with trusted publishing"
    )


def test_release_recovery_is_tag_scoped_and_hash_verifying() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "recover-release.yml"
    assert workflow_path.is_file()
    raw = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)

    assert "workflow_dispatch" in raw
    assert workflow["permissions"] == {"contents": "write", "id-token": "none"}
    assert "verify_existing_distribution_hashes.py" in raw
    assert "gh release create" in raw
    assert "--verify-tag" in raw
    assert "gh release upload" not in raw
    assert "pypa/gh-action-pypi-publish" not in raw


def test_release_runbook_describes_partial_success_recovery() -> None:
    runbook = (ROOT / "docs" / "release-runbook.md").read_text(encoding="utf-8")

    assert "PyPI成功・GitHub Release失敗" in runbook
    assert "artifactのSHA-256" in runbook
    assert "同一versionを再公開しない" in runbook
    assert "artifact期限切れ" in runbook
