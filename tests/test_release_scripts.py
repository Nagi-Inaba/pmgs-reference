from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
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


_select_wheel = cast(Callable[[Path, str], Path], _load_script()._select_wheel)


def test_select_wheel_ignores_other_project_versions(tmp_path: Path) -> None:
    (tmp_path / "pmgs_reference-0.1.0-py3-none-any.whl").touch()
    expected = tmp_path / "pmgs_reference-0.3.0-py3-none-any.whl"
    expected.touch()

    assert _select_wheel(tmp_path, "0.3.0") == expected.resolve()


def test_select_wheel_rejects_zero_or_multiple_current_version_wheels(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"version 0\.3\.0, found 0"):
        _select_wheel(tmp_path, "0.3.0")

    (tmp_path / "pmgs_reference-0.3.0-py3-none-any.whl").touch()
    (tmp_path / "pmgs_reference-0.3.0-cp312-none-any.whl").touch()
    with pytest.raises(RuntimeError, match=r"version 0\.3\.0, found 2"):
        _select_wheel(tmp_path, "0.3.0")


def test_wheel_verifier_does_not_hardcode_the_expected_cli_version() -> None:
    raw = (ROOT / "scripts" / "verify_wheel_install.py").read_text(encoding="utf-8")

    assert 'version != "pmgs 0.3.0"' not in raw
    assert 'expected_version = f"pmgs {project_version}"' in raw
