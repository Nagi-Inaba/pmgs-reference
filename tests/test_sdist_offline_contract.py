from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_verifier() -> ModuleType:
    path = ROOT / "scripts" / "verify_sdist_install.py"
    spec = importlib.util.spec_from_file_location("pmgs_verify_sdist_install", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sdist_subprocesses_run_with_uv_offline() -> None:
    module = _load_verifier()
    result = module._run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('UV_OFFLINE', ''))",
        ]
    )

    assert result.stdout.strip() == "1"
