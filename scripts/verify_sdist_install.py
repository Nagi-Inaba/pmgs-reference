"""Build an isolated wheel from the sdist and run the installed-wheel E2E contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
_MAX_MEMBERS = 10_000
_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def _project_version() -> str:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise RuntimeError("pyproject.toml does not declare a project version")
    return cast(str, project["version"])


def _select_sdist(dist_dir: Path, version: str) -> Path:
    expected_names = {
        f"pmgs_reference-{version}.tar.gz",
        f"pmgs-reference-{version}.tar.gz",
    }
    archives = sorted(
        path.resolve()
        for path in dist_dir.resolve().glob("*.tar.gz")
        if path.name in expected_names
    )
    if len(archives) != 1:
        raise RuntimeError(
            f"expected exactly one PMGS sdist for version {version}, found {len(archives)}"
        )
    return archives[0]


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise RuntimeError("sdist contains an unsafe member path")
    member_path = PurePosixPath(name)
    if member_path.is_absolute() or any(part in {"", ".", ".."} for part in member_path.parts):
        raise RuntimeError("sdist contains an unsafe member path")
    if member_path.parts and ":" in member_path.parts[0]:
        raise RuntimeError("sdist contains an unsafe member path")
    return member_path


def _extract_sdist(archive_path: Path, destination: Path) -> Path:
    archive_path = archive_path.resolve()
    expected_top_level = archive_path.name.removesuffix(".tar.gz")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    total_bytes = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise RuntimeError("sdist contains too many members")
        parsed: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        top_levels: set[str] = set()
        seen_paths: set[PurePosixPath] = set()
        for member in members:
            member_path = _safe_member_path(member.name)
            if member_path in seen_paths:
                raise RuntimeError("sdist contains a duplicate member path")
            seen_paths.add(member_path)
            top_levels.add(member_path.parts[0])
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("sdist contains a link or special file")
            if member.isfile():
                if member.size < 0:
                    raise RuntimeError("sdist contains an invalid file size")
                total_bytes += member.size
                if total_bytes > _MAX_UNCOMPRESSED_BYTES:
                    raise RuntimeError("sdist exceeds the uncompressed size limit")
            parsed.append((member, member_path))
        if top_levels != {expected_top_level}:
            raise RuntimeError("sdist must contain one expected top-level directory")
        for member, member_path in parsed:
            target = destination.joinpath(*member_path.parts)
            try:
                target.relative_to(destination)
            except ValueError as exc:  # pragma: no cover - guarded by PurePosixPath checks
                raise RuntimeError("sdist member escapes the extraction root") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("sdist regular file could not be read")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    root = destination / expected_top_level
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError("sdist does not contain pyproject.toml")
    return root


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_PYTHON_PREFERENCE": "only-system",
        }
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {command[0]}\n"
            f"{completed.stderr[-2000:]}"
        )
    return completed


def _select_wheel(directory: Path, version: str) -> Path:
    matches = sorted(directory.glob(f"pmgs_reference-{version}-*.whl"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one sdist-derived wheel for version {version}, found {len(matches)}"
        )
    return matches[0].resolve()


def _sha256_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest().upper()


def _wheel_contract(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("wheel contains a duplicate member path")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise RuntimeError("wheel METADATA member is missing or ambiguous")
        dist_info_prefix = metadata_names[0].removesuffix("METADATA")
        runtime_hashes: dict[str, str] = {}
        metadata_hashes: dict[str, str] = {}
        for name in names:
            if name.endswith("/"):
                continue
            payload = archive.read(name)
            if name.startswith(dist_info_prefix):
                relative = name.removeprefix(dist_info_prefix)
                if relative != "RECORD":
                    metadata_hashes[relative] = _sha256_bytes(payload)
            else:
                runtime_hashes[name] = _sha256_bytes(payload)
        return {
            "runtime_hashes": runtime_hashes,
            "metadata_hashes": metadata_hashes,
        }


def _compare_wheels(reference: Path, rebuilt: Path) -> None:
    if _wheel_contract(reference) != _wheel_contract(rebuilt):
        raise RuntimeError(
            "sdist-derived wheel runtime files or metadata differ from the release wheel"
        )


def verify_sdist(dist_dir: Path, source: Path, version: str) -> dict[str, object]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv executable not found")
    sdist = _select_sdist(dist_dir, version)
    reference_wheels = sorted(dist_dir.resolve().glob(f"pmgs_reference-{version}-*.whl"))
    if len(reference_wheels) != 1:
        raise RuntimeError(
            "expected exactly one release wheel for version "
            f"{version}, found {len(reference_wheels)}"
        )
    with tempfile.TemporaryDirectory(prefix="pmgs-sdist-e2e-") as temporary_name:
        temporary = Path(temporary_name).resolve()
        extracted = _extract_sdist(sdist, temporary / "source")
        required_files = (
            "LICENSE",
            "README.md",
            "README.en.md",
            "pyproject.toml",
            "src/pmgs_reference/__init__.py",
        )
        missing = [name for name in required_files if not (extracted / name).is_file()]
        if missing:
            raise RuntimeError(f"sdist is missing required file: {missing[0]}")
        rebuilt_dir = temporary / "rebuilt"
        rebuilt_dir.mkdir()
        _run(
            [uv, "build", "--wheel", "--no-sources", "--out-dir", str(rebuilt_dir)],
            cwd=extracted,
        )
        rebuilt_wheel = _select_wheel(rebuilt_dir, version)
        _compare_wheels(reference_wheels[0].resolve(), rebuilt_wheel)
        _run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_wheel_install.py"),
                "--dist-dir",
                str(rebuilt_dir),
                "--source",
                str(source.resolve()),
            ],
            cwd=ROOT,
        )
    return {
        "schema_version": "1.0",
        "status": "ready",
        "version": version,
        "sdist": sdist.name,
        "wheel_contract": "matched",
        "installed_runtime": "verified",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    result = verify_sdist(args.dist_dir, args.source, _project_version())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
