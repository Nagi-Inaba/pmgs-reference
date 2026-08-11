"""Verify that a release tag and the package version identify the same release."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    project = tomllib.loads(args.project.read_text(encoding="utf-8"))
    version = project["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise SystemExit("pyproject.toml must contain a stable semantic version")
    expected = f"v{version}"
    if args.tag != expected:
        raise SystemExit(f"release tag {args.tag!r} does not match package version {expected!r}")
    print(f"release tag verified: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
