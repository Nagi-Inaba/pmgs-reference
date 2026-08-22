from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_python_313_is_covered_by_source_and_installed_wheel_ci() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    source_matrix = jobs["python"]["strategy"]["matrix"]
    included = source_matrix.get("include", [])

    assert {"os": "ubuntu-latest", "python-version": "3.13"} in included

    wheel_job = jobs["python-313-wheel-e2e"]
    assert wheel_job["runs-on"] == "ubuntu-latest"
    setup_step = next(
        step for step in wheel_job["steps"] if step["name"] == "Install uv and Python"
    )
    assert setup_step["with"]["python-version"] == "3.13"
    assert any(
        "scripts/verify_wheel_install.py" in str(step.get("run", ""))
        for step in wheel_job["steps"]
    )


def test_contributor_python_versions_match_supported_minors() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Python 3.12, 3.13, or 3.14" in contributing
