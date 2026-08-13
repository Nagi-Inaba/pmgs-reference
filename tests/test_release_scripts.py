from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    script = ROOT / "scripts" / "verify_wheel_install.py"
    spec = importlib.util.spec_from_file_location("verify_wheel_install", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("verify_wheel_install.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_named_script(name: str) -> ModuleType:
    script = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(script.stem, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_select_wheel = cast(Callable[[Path, str], Path], _load_script()._select_wheel)


def test_select_wheel_ignores_other_project_versions(tmp_path: Path) -> None:
    (tmp_path / "pmgs_reference-0.1.0-py3-none-any.whl").touch()
    expected = tmp_path / "pmgs_reference-0.4.0-py3-none-any.whl"
    expected.touch()

    assert _select_wheel(tmp_path, "0.4.0") == expected.resolve()


def test_select_wheel_rejects_zero_or_multiple_current_version_wheels(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"version 0\.4\.0, found 0"):
        _select_wheel(tmp_path, "0.4.0")

    (tmp_path / "pmgs_reference-0.4.0-py3-none-any.whl").touch()
    (tmp_path / "pmgs_reference-0.4.0-cp312-none-any.whl").touch()
    with pytest.raises(RuntimeError, match=r"version 0\.4\.0, found 2"):
        _select_wheel(tmp_path, "0.4.0")


def test_wheel_verifier_does_not_hardcode_the_expected_cli_version() -> None:
    raw = (ROOT / "scripts" / "verify_wheel_install.py").read_text(encoding="utf-8")

    assert 'version != "pmgs 0.4.0"' not in raw
    assert 'expected_version = f"pmgs {project_version}"' in raw


def test_wheel_verifier_forces_utf8_in_child_processes() -> None:
    module = _load_script()

    environment = module._utf8_environment(
        {"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252", "KEEP": "value"}
    )

    assert environment == {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "KEEP": "value",
    }


def test_synthetic_determinism_report_is_valid_and_path_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_named_script("verify_synthetic_determinism.py")
    source_digest = "A" * 64
    logical_digest = "B" * 64
    tree_digest = "C" * 64
    counts = {name: index for index, name in enumerate(module.SEMANTIC_TABLES)}
    monkeypatch.setattr(
        module,
        "build_database",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_manifest_sha256=source_digest,
            logical_digest=logical_digest,
        ),
    )
    monkeypatch.setattr(
        module,
        "validate_database",
        lambda _path: SimpleNamespace(
            valid=True,
            logical_digest=logical_digest,
            counts=counts,
            checks={"integrity": {"match": True}},
        ),
    )
    monkeypatch.setattr(
        module,
        "export_public",
        lambda *_args, **_kwargs: SimpleNamespace(
            tree_sha256=tree_digest,
            object_count=12,
            total_bytes=345,
        ),
    )
    monkeypatch.setattr(
        module,
        "validate_public_export",
        lambda _path: SimpleNamespace(
            valid=True,
            tree_sha256=tree_digest,
            object_count=12,
            total_bytes=345,
        ),
    )
    report = module.build_report(
        ROOT / "tests" / "fixtures" / "synthetic_pmgs",
        ROOT / "tests" / "fixtures" / "publication-policy.yaml",
        platform_name="Windows",
    )
    repeated = module.build_report(
        ROOT / "tests" / "fixtures" / "synthetic_pmgs",
        ROOT / "tests" / "fixtures" / "publication-policy.yaml",
        platform_name="Linux",
    )

    assert report["valid"] is True
    assert report["platform"] == "Windows"
    assert report["stable_contract"] == repeated["stable_contract"]
    contract = report["stable_contract"]
    assert contract["source_manifest_sha256"]
    assert contract["database"]["logical_digest"]
    assert contract["database"]["validation_checks_sha256"]
    assert contract["public_export"]["tree_sha256"]
    assert contract["public_export"]["object_count"] > 0
    assert contract["public_export"]["total_bytes"] > 0
    assert str(tmp_path) not in json.dumps(report)


def test_synthetic_determinism_resolves_temporary_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_named_script("verify_synthetic_determinism.py")
    lexical_root = tmp_path / "parent" / ".." / "canonical"
    observed: dict[str, Path] = {}

    class TemporaryDirectory:
        def __init__(self, *, prefix: str) -> None:
            assert prefix == "pmgs-determinism-"

        def __enter__(self) -> str:
            return str(lexical_root)

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", TemporaryDirectory)
    monkeypatch.setattr(
        module,
        "_copy_synthetic_source",
        lambda _source, target: observed.setdefault("source", target),
    )
    monkeypatch.setattr(
        module,
        "build_database",
        lambda _source, _release, database: (
            observed.setdefault("database", database),
            SimpleNamespace(source_manifest_sha256="A" * 64, logical_digest="B" * 64),
        )[1],
    )
    counts = {name: 1 for name in module.SEMANTIC_TABLES}
    monkeypatch.setattr(
        module,
        "validate_database",
        lambda _path: SimpleNamespace(
            valid=True, logical_digest="B" * 64, counts=counts, checks={}
        ),
    )
    monkeypatch.setattr(
        module,
        "export_public",
        lambda _database, _policy, public_root, **_kwargs: (
            observed.setdefault("public", public_root),
            SimpleNamespace(tree_sha256="C" * 64, object_count=1, total_bytes=1),
        )[1],
    )
    monkeypatch.setattr(
        module,
        "validate_public_export",
        lambda public_root: (
            observed.setdefault("validated", public_root),
            SimpleNamespace(valid=True, tree_sha256="C" * 64, object_count=1, total_bytes=1),
        )[1],
    )

    module.build_report(tmp_path / "source", tmp_path / "policy.yaml", platform_name="Windows")

    resolved_root = lexical_root.resolve()
    assert observed == {
        "source": resolved_root / module.RELEASE_ID,
        "database": resolved_root / "pmgs.sqlite",
        "public": resolved_root / "public",
        "validated": resolved_root / "public",
    }


def test_synthetic_pdf_generation_is_byte_reproducible(tmp_path: Path) -> None:
    module = _load_named_script("verify_synthetic_determinism.py")
    first = tmp_path / "first"
    second = tmp_path / "second"
    module._copy_synthetic_source(ROOT / "tests" / "fixtures" / "synthetic_pmgs", first)
    module._copy_synthetic_source(ROOT / "tests" / "fixtures" / "synthetic_pmgs", second)

    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files


def test_compare_determinism_reports_requires_three_platforms_and_equal_contracts(
    tmp_path: Path,
) -> None:
    module = _load_named_script("compare_determinism_reports.py")
    paths: list[Path] = []
    stable_contract = {
        "source_manifest_sha256": "A" * 64,
        "database": {
            "logical_digest": "B" * 64,
            "semantic_table_counts": {"concept": 1},
            "validation_checks_sha256": "C" * 64,
        },
        "public_export": {
            "tree_sha256": "D" * 64,
            "object_count": 2,
            "total_bytes": 3,
        },
    }
    for platform in ("Windows", "Linux", "macOS"):
        path = tmp_path / f"{platform}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "platform": platform,
                    "release_id": "JPPM2099001",
                    "stable_contract": stable_contract,
                    "valid": True,
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)

    result = module.compare_reports(paths)
    assert result["ready"] is True
    assert result["platforms"] == ["Linux", "Windows", "macOS"]

    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    payload["stable_contract"]["database"]["logical_digest"] = "E" * 64
    paths[-1].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="differs"):
        module.compare_reports(paths)
