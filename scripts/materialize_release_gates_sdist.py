# ruff: noqa: E501
"""Materialize the reviewed release-gate patch for temporary CI handoff."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"materialization anchor not found: {label}")
    return text.replace(old, new, 1)


def main() -> int:
    test_path = ROOT / "tests" / "test_release_scripts.py"
    text = test_path.read_text(encoding="utf-8")
    replacements = (
        (
            '''    metadata = (\n        "Metadata-Version: 2.4\\n"\n        "Name: pmgs-reference\\n"\n        "Version: 0.4.0\\n"\n        "Requires-Python: >=3.12\\n\\n"\n    ).encode()\n''',
            '''    metadata = (\n        b"Metadata-Version: 2.4\\n"\n        b"Name: pmgs-reference\\n"\n        b"Version: 0.4.0\\n"\n        b"Requires-Python: >=3.12\\n\\n"\n    )\n''',
            "metadata bytes",
        ),
        (
            '''    with pytest.warns(UserWarning, match="Duplicate name"):\n        with zipfile.ZipFile(rebuilt, "a") as archive:\n            archive.writestr("pmgs_reference/__init__.py", b"VERSION = 'duplicate'\\n")\n''',
            '''    with (\n        pytest.warns(UserWarning, match="Duplicate name"),\n        zipfile.ZipFile(rebuilt, "a") as archive,\n    ):\n        archive.writestr("pmgs_reference/__init__.py", b"VERSION = 'duplicate'\\n")\n''',
            "duplicate wheel context",
        ),
        (
            '''    result = module.verify_distribution_set(tmp_path, "0.4.0")\n''',
            '''    (tmp_path / ".gitignore").write_text("*\\n", encoding="utf-8")\n    result = module.verify_distribution_set(tmp_path, "0.4.0")\n''',
            "uv marker acceptance",
        ),
        (
            '''    assert set(result["sha256"]) == {wheel.name, sdist.name}\n\n    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")\n''',
            '''    assert set(result["sha256"]) == {wheel.name, sdist.name}\n\n    (tmp_path / ".gitignore").unlink()\n    (tmp_path / ".gitignore").mkdir()\n    with pytest.raises(RuntimeError, match="non-file uv build marker"):\n        module.verify_distribution_set(tmp_path, "0.4.0")\n    (tmp_path / ".gitignore").rmdir()\n\n    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")\n''',
            "uv marker boundary",
        ),
    )
    for old, new, label in replacements:
        text = _replace_once(text, old, new, label=label)
    test_path.write_text(text, encoding="utf-8")

    verifier_path = ROOT / "scripts" / "verify_distribution_set.py"
    verifier = verifier_path.read_text(encoding="utf-8")
    old_marker_boundary = '''    if symbolic_links:\n        raise RuntimeError(\n            f"symbolic link distribution entry: {', '.join(symbolic_links)}"\n        )\n    expected_names = {\n'''
    new_marker_boundary = '''    if symbolic_links:\n        raise RuntimeError(\n            f"symbolic link distribution entry: {', '.join(symbolic_links)}"\n        )\n    uv_marker = root / ".gitignore"\n    if uv_marker.exists() and not uv_marker.is_file():\n        raise RuntimeError("non-file uv build marker: .gitignore")\n    entries = [path for path in entries if path.name != ".gitignore"]\n    expected_names = {\n'''
    verifier_path.write_text(
        _replace_once(
            verifier,
            old_marker_boundary,
            new_marker_boundary,
            label="distribution verifier uv marker",
        ),
        encoding="utf-8",
    )

    release_path = ROOT / ".github" / "workflows" / "release.yml"
    release = release_path.read_text(encoding="utf-8")
    for old, new in (
        ("  build-distributions:\n", "  build:\n"),
        ("    needs: build-distributions\n", "    needs: build\n"),
        ("      - build-distributions\n", "      - build\n"),
    ):
        if old not in release:
            raise RuntimeError(f"release workflow compatibility anchor not found: {old!r}")
        release = release.replace(old, new)
    release_path.write_text(release, encoding="utf-8")

    contract_path = ROOT / "tests" / "test_release_gate_contract.py"
    contract = contract_path.read_text(encoding="utf-8")
    contract_path.write_text(
        _replace_once(
            contract,
            '"build-distributions"',
            '"build"',
            label="release gate build job",
        ),
        encoding="utf-8",
    )

    runbook_path = ROOT / "docs" / "release-runbook.md"
    runbook = runbook_path.read_text(encoding="utf-8")
    runbook_path.write_text(
        _replace_once(
            runbook,
            "`build-distributions`",
            "`build`",
            label="release runbook build job",
        ),
        encoding="utf-8",
    )

    project_contract_path = ROOT / "tests" / "test_project_contracts.py"
    project_contract = project_contract_path.read_text(encoding="utf-8")
    old_artifact_assertion = '    assert raw.count("name: python-distributions") == 3\n'
    new_artifact_assertion = "\n".join(
        (
            "    distribution_uploads = [",
            "        step",
            '        for step in jobs["build"]["steps"]',
            '        if "upload-artifact@" in str(step.get("uses", ""))',
            '        and step.get("with", {}).get("name") == "python-distributions"',
            "    ]",
            "    assert len(distribution_uploads) == 1",
            '    for job_name in ("verify-distributions", "publish-pypi", "publish-github"):',
            "        distribution_downloads = [",
            "            step",
            '            for step in jobs[job_name]["steps"]',
            '            if "download-artifact@" in str(step.get("uses", ""))',
            '            and step.get("with", {}).get("name") == "python-distributions"',
            "        ]",
            "        assert len(distribution_downloads) == 1",
            "",
        )
    )
    project_contract_path.write_text(
        _replace_once(
            project_contract,
            old_artifact_assertion,
            new_artifact_assertion,
            label="project distribution artifact contract",
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
