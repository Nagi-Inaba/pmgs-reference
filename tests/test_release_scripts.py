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


def _write_tar(path: Path, members: list[tuple[str, bytes, str]]) -> None:
    import io
    import tarfile

    with tarfile.open(path, "w:gz") as archive:
        for name, content, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "target"
                archive.addfile(info)
            else:  # pragma: no cover - test helper guard
                raise AssertionError(kind)


def test_select_sdist_ignores_other_project_versions(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")
    (tmp_path / "pmgs_reference-0.3.0.tar.gz").touch()
    expected = tmp_path / "pmgs_reference-0.4.0.tar.gz"
    expected.touch()

    assert module._select_sdist(tmp_path, "0.4.0") == expected.resolve()


def test_select_sdist_rejects_zero_or_multiple_current_version_archives(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")

    with pytest.raises(RuntimeError, match=r"version 0\.4\.0, found 0"):
        module._select_sdist(tmp_path, "0.4.0")

    (tmp_path / "pmgs_reference-0.4.0.tar.gz").touch()
    (tmp_path / "pmgs-reference-0.4.0.tar.gz").touch()
    with pytest.raises(RuntimeError, match=r"version 0\.4\.0, found 2"):
        module._select_sdist(tmp_path, "0.4.0")


def test_sdist_extraction_rejects_traversal_absolute_and_links(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")
    cases = {
        "traversal": [("pmgs_reference-0.4.0/../escape", b"x", "file")],
        "absolute": [("/absolute", b"x", "file")],
        "symlink": [("pmgs_reference-0.4.0/link", b"", "symlink")],
    }

    for name, members in cases.items():
        archive = tmp_path / f"{name}.tar.gz"
        _write_tar(archive, members)
        with pytest.raises(RuntimeError):
            module._extract_sdist(archive, tmp_path / name)


def test_sdist_extraction_requires_one_expected_top_level_directory(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")
    archive = tmp_path / "pmgs_reference-0.4.0.tar.gz"
    _write_tar(
        archive,
        [
            ("pmgs_reference-0.4.0/pyproject.toml", b"[project]\n", "file"),
            ("unexpected/file.txt", b"x", "file"),
        ],
    )

    with pytest.raises(RuntimeError, match="top-level"):
        module._extract_sdist(archive, tmp_path / "extract")


def test_distribution_set_requires_exact_current_wheel_and_sdist(tmp_path: Path) -> None:
    import io
    import tarfile
    import zipfile

    module = _load_named_script("verify_distribution_set.py")
    wheel = tmp_path / "pmgs_reference-0.4.0-py3-none-any.whl"
    sdist = tmp_path / "pmgs_reference-0.4.0.tar.gz"
    metadata = (
        b"Metadata-Version: 2.4\nName: pmgs-reference\nVersion: 0.4.0\nRequires-Python: >=3.12\n\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pmgs_reference-0.4.0.dist-info/METADATA", metadata)
    with tarfile.open(sdist, "w:gz") as archive:
        info = tarfile.TarInfo("pmgs_reference-0.4.0/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))

    (tmp_path / ".gitignore").write_text("*\n", encoding="utf-8")
    result = module.verify_distribution_set(tmp_path, "0.4.0")

    assert result["files"] == [wheel.name, sdist.name]
    assert set(result["sha256"]) == {wheel.name, sdist.name}

    (tmp_path / ".gitignore").unlink()
    (tmp_path / ".gitignore").mkdir()
    with pytest.raises(RuntimeError, match="non-file uv build marker"):
        module.verify_distribution_set(tmp_path, "0.4.0")
    (tmp_path / ".gitignore").rmdir()

    (tmp_path / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected distribution artifact"):
        module.verify_distribution_set(tmp_path, "0.4.0")


def _write_test_wheel(
    path: Path,
    *,
    payload: bytes,
    wheel_metadata: bytes = b"Wheel-Version: 1.0\n",
) -> None:
    import zipfile

    metadata = b"Metadata-Version: 2.4\nName: pmgs-reference\nVersion: 0.4.0\n\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("pmgs_reference/__init__.py", payload)
        archive.writestr("pmgs_reference-0.4.0.dist-info/METADATA", metadata)
        archive.writestr("pmgs_reference-0.4.0.dist-info/WHEEL", wheel_metadata)
        archive.writestr(
            "pmgs_reference-0.4.0.dist-info/entry_points.txt",
            b"[console_scripts]\npmgs=pmgs_reference.cli:main\n",
        )
        archive.writestr("pmgs_reference-0.4.0.dist-info/RECORD", b"")


def test_sdist_wheel_comparison_rejects_runtime_payload_drift(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")
    reference = tmp_path / "reference.whl"
    rebuilt = tmp_path / "rebuilt.whl"
    _write_test_wheel(reference, payload=b"VERSION = 'reference'\n")
    _write_test_wheel(rebuilt, payload=b"VERSION = 'rebuilt'\n")

    with pytest.raises(RuntimeError, match="runtime files"):
        module._compare_wheels(reference, rebuilt)


def test_distribution_set_rejects_symlinked_artifacts(tmp_path: Path) -> None:
    module = _load_named_script("verify_distribution_set.py")
    real_wheel = tmp_path.with_name(tmp_path.name + "-real-wheel")
    real_wheel.write_bytes(b"wheel")
    wheel = tmp_path / "pmgs_reference-0.4.0-py3-none-any.whl"
    try:
        wheel.symlink_to(real_wheel)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    (tmp_path / "pmgs_reference-0.4.0.tar.gz").write_bytes(b"sdist")

    with pytest.raises(RuntimeError, match="symbolic link"):
        module.verify_distribution_set(tmp_path, "0.4.0")


def test_sdist_wheel_comparison_rejects_wheel_metadata_drift(tmp_path: Path) -> None:
    module = _load_named_script("verify_sdist_install.py")
    reference = tmp_path / "reference.whl"
    rebuilt = tmp_path / "rebuilt.whl"
    _write_test_wheel(reference, payload=b"VERSION = 'same'\n")
    _write_test_wheel(
        rebuilt,
        payload=b"VERSION = 'same'\n",
        wheel_metadata=b"Wheel-Version: 1.0\nGenerator: altered\n",
    )

    with pytest.raises(RuntimeError, match="metadata"):
        module._compare_wheels(reference, rebuilt)


def test_sdist_wheel_comparison_rejects_duplicate_members(tmp_path: Path) -> None:
    import zipfile

    module = _load_named_script("verify_sdist_install.py")
    reference = tmp_path / "reference.whl"
    rebuilt = tmp_path / "rebuilt.whl"
    _write_test_wheel(reference, payload=b"VERSION = 'same'\n")
    _write_test_wheel(rebuilt, payload=b"VERSION = 'same'\n")
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(rebuilt, "a") as archive,
    ):
        archive.writestr("pmgs_reference/__init__.py", b"VERSION = 'duplicate'\n")

    with pytest.raises(RuntimeError, match="duplicate"):
        module._compare_wheels(reference, rebuilt)
