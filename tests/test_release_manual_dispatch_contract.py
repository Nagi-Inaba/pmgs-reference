from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_can_publish_an_existing_tag_by_dispatch() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    manual_ref = (
        "$"
        + "{{ github.event_name == 'workflow_dispatch' && inputs.release_tag || github.ref }}"
    )
    manual_tag = (
        "$"
        + "{{ github.event_name == 'workflow_dispatch' && inputs.release_tag || github.ref_name }}"
    )

    assert "workflow_dispatch:" in workflow
    assert "release_tag:" in workflow
    assert workflow.count(manual_ref) == 7
    assert workflow.count(manual_tag) == 2
    assert "environment:\n      name: pypi" in workflow
