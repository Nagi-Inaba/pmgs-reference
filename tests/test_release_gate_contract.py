from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _release_workflow() -> dict[str, object]:
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )


def _needs(job: dict[str, object]) -> set[str]:
    value = job.get("needs", [])
    if isinstance(value, str):
        return {value}
    assert isinstance(value, list)
    return {str(item) for item in value}


def test_release_publish_waits_for_all_platform_and_artifact_gates() -> None:
    workflow = _release_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    expected = {
        "build",
        "verify-linux",
        "verify-windows",
        "verify-macos",
        "compare-synthetic-determinism",
        "verify-distributions",
        "verify-worker",
    }
    assert expected <= set(jobs)
    publish = jobs["publish-pypi"]
    assert isinstance(publish, dict)
    assert expected <= _needs(publish)


def test_release_platform_gates_verify_source_wheel_sdist_and_determinism() -> None:
    workflow = _release_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    expected_os = {
        "verify-linux": "ubuntu-latest",
        "verify-windows": "windows-latest",
        "verify-macos": "macos-latest",
    }

    for job_id, operating_system in expected_os.items():
        job = jobs[job_id]
        assert isinstance(job, dict)
        assert job["runs-on"] == operating_system
        assert _needs(job) == {"build"}
        serialized = yaml.safe_dump(job, sort_keys=False)
        assert "scripts/verify_wheel_install.py" in serialized
        assert "scripts/verify_sdist_install.py" in serialized
        assert "scripts/verify_synthetic_determinism.py" in serialized
        assert "uv run --frozen pytest -q" in serialized


def test_release_distribution_gate_verifies_exact_fixed_artifact_set() -> None:
    workflow = _release_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["verify-distributions"]
    assert isinstance(job, dict)
    assert _needs(job) == {"build"}
    serialized = yaml.safe_dump(job, sort_keys=False)
    assert "scripts/verify_distribution_set.py" in serialized


def test_release_worker_gate_is_required_before_publish() -> None:
    workflow = _release_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    worker = jobs["verify-worker"]
    assert isinstance(worker, dict)
    serialized = yaml.safe_dump(worker, sort_keys=False)
    assert "npm --prefix worker ci" in serialized
    assert "npm --prefix worker run verify" in serialized


def test_release_runbook_documents_three_os_and_sdist_gate() -> None:
    runbook = (ROOT / "docs" / "release-runbook.md").read_text(encoding="utf-8")

    assert "3 OS release gate" in runbook
    assert "verify_sdist_install.py" in runbook
    assert "sdist由来wheel" in runbook


def test_pull_request_ci_runs_sdist_e2e_on_all_three_operating_systems() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    wheel_e2e = jobs["wheel-e2e"]
    assert isinstance(wheel_e2e, dict)
    assert wheel_e2e["strategy"]["matrix"]["os"] == [
        "ubuntu-latest",
        "windows-latest",
        "macos-latest",
    ]
    serialized = yaml.safe_dump(wheel_e2e, sort_keys=False)
    assert "scripts/verify_sdist_install.py" in serialized
