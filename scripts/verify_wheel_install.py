"""Install the built wheel into an isolated uv tool environment and exercise setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]


def _utf8_environment(environment: dict[str, str]) -> dict[str, str]:
    configured = environment.copy()
    configured.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return configured


def _run(command: list[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {command[0]}\n"
            f"{completed.stderr[-2000:]}"
        )
    return completed


def _json_command(command: list[str], *, environment: dict[str, str]) -> dict[str, object]:
    completed = _run(command, environment=environment)
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"command did not return one JSON object: {command[0]}")
    return cast(dict[str, object], parsed)


def _copy_synthetic_source(source: Path, target: Path) -> None:
    import pymupdf

    shutil.copytree(source, target)
    pdf_path = target / "REFERENCE" / "IPC_TEIGI" / "G06F3-048.pdf"
    pdf_path.parent.mkdir(parents=True)
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic IPC definition G06F3/048")
        document.set_metadata({})
        document.save(pdf_path, no_new_id=True, reproducible=True)
    finally:
        document.close()


def _project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise RuntimeError("pyproject.toml does not declare a project version")
    return project["version"]


def _select_wheel(dist_dir: Path, version: str) -> Path:
    prefix = f"pmgs_reference-{version}-"
    wheels = sorted(
        path.resolve()
        for path in dist_dir.resolve().glob("pmgs_reference-*.whl")
        if path.name.startswith(prefix)
    )
    if len(wheels) != 1:
        raise RuntimeError(
            f"expected exactly one PMGS wheel for version {version}, found {len(wheels)}"
        )
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    project_version = _project_version()
    wheel = _select_wheel(args.dist_dir, project_version)
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv executable not found")

    with tempfile.TemporaryDirectory(prefix="pmgs-wheel-e2e-") as temporary_name:
        temporary = Path(temporary_name)
        tool_dir = temporary / "tools"
        bin_dir = temporary / "bin"
        environment = _utf8_environment(os.environ)
        environment.update(
            {
                "UV_TOOL_DIR": str(tool_dir),
                "UV_TOOL_BIN_DIR": str(bin_dir),
                "UV_PYTHON_DOWNLOADS": "never",
                "UV_PYTHON_PREFERENCE": "only-system",
            }
        )
        _run(
            [
                uv,
                "tool",
                "install",
                "--force",
                "--python",
                sys.executable,
                str(wheel),
            ],
            environment=environment,
        )
        executable = bin_dir / ("pmgs.exe" if os.name == "nt" else "pmgs")
        if not executable.is_file():
            raise RuntimeError(f"pmgs console script was not installed: {executable}")
        source = temporary / "JPPM2099001"
        _copy_synthetic_source(args.source.resolve(), source)
        data_root = temporary / "data-root"
        setup_command = [
            str(executable),
            "setup",
            str(source),
            "--release",
            "JPPM2099001",
            "--data-dir",
            str(data_root),
            "--client",
            "none",
            "--no-register",
            "--non-interactive",
            "--json",
        ]
        first = _json_command(setup_command, environment=environment)
        second = _json_command(setup_command, environment=environment)
        doctor = _json_command(
            [str(executable), "doctor", "--data-dir", str(data_root), "--json"],
            environment=environment,
        )
        lookup = _json_command(
            [
                str(executable),
                "lookup",
                "fi",
                "G06F3/048",
                "--data-dir",
                str(data_root),
                "--json",
            ],
            environment=environment,
        )
        version = _run([str(executable), "--version"], environment=environment).stdout.strip()
        if first.get("status") != "ready":
            raise RuntimeError(f"first setup did not become ready: {first.get('status')}")
        if second.get("status") != "already_ready":
            raise RuntimeError(f"second setup was not idempotent: {second.get('status')}")
        if doctor.get("ok") is not True:
            raise RuntimeError("installed-wheel doctor failed")
        if (
            lookup.get("schema_version") != "2.0"
            or lookup.get("match_status") not in {"exact", "normalized_exact"}
            or not lookup.get("reference_date")
        ):
            raise RuntimeError("installed-wheel lookup failed")
        tool_names = doctor.get("tool_names")
        if tool_names != [
            "lookup_classification",
            "search_pmgs",
            "get_pmgs_document",
        ]:
            raise RuntimeError("installed-wheel MCP tool contract failed")
        expected_version = f"pmgs {project_version}"
        if version != expected_version:
            raise RuntimeError(f"unexpected installed version: {version}")
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "ready",
                    "first_setup": first["status"],
                    "second_setup": second["status"],
                    "doctor": doctor["ok"],
                    "lookup": lookup["match_status"],
                    "mcp_tools": tool_names,
                    "version": version,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
