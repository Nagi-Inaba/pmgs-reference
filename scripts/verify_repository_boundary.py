from __future__ import annotations

import re
import subprocess
from pathlib import Path

MAX_TRACKED_BYTES = 10 * 1024 * 1024
SYNTHETIC_ROOT = "tests/fixtures/synthetic_pmgs/"
ALLOWED_PDFS = {
    "docs/evidence/jpo-api-handbook-v1.4.pdf",
    "docs/evidence/jpo-api-handbook-v2.0.pdf",
    "docs/evidence/jpo-bulk-download-terms-2026.pdf",
}
SOURCE_LIKE_SUFFIXES = {".csv", ".html", ".xml", ".xsl", ".pdf"}
FORBIDDEN_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
}
SECRET_PATTERNS = (
    re.compile(r"gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_" + r"pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk" + r"-[A-Za-z0-9]{20,}"),
    re.compile(r"AK" + r"IA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"https?://[^/\s:@]+:[^@\s/]+@"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:" + r"\\[^\s`\"']+"),
    re.compile(r"/" + r"home/[^\s`\"']+"),
    re.compile(r"/" + r"Users/[^\s`\"']+"),
)
ALLOWED_LOCAL_PATH_PREFIXES = {
    "README.md": ("C:" + "\\path\\to\\",),
    "docs/local-interfaces.md": (
        "C:" + "\\path\\to\\",
        "C:" + "\\\\path\\\\to\\\\",
    ),
    "tests/test_public_export.py": (
        "B:" + "\\nnext",
        "C:" + "\\Users\\Example\\",
        "/" + "home/example/",
    ),
}


def candidate_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
    )
    return [
        Path(raw.decode("utf-8", errors="surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def is_allowed_source_like(relative: str, suffix: str) -> bool:
    if suffix == ".pdf":
        return relative in ALLOWED_PDFS
    return relative.startswith(SYNTHETIC_ROOT)


def content_errors(path: Path, relative: str) -> list[str]:
    if path.suffix.lower() == ".pdf":
        return []

    raw = path.read_bytes()
    if b"\0" in raw[:8192]:
        return []

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{relative}: tracked text is not UTF-8"]

    errors = [
        f"{relative}: credential or private-key pattern detected"
        for pattern in SECRET_PATTERNS
        if pattern.search(text)
    ]
    for pattern in LOCAL_PATH_PATTERNS:
        for match in pattern.finditer(text):
            allowed_prefixes = ALLOWED_LOCAL_PATH_PREFIXES.get(relative, ())
            if not match.group(0).startswith(allowed_prefixes):
                errors.append(f"{relative}: local absolute path detected")
                break
    return errors


def verify_repository() -> tuple[list[str], int]:
    errors: list[str] = []
    paths = candidate_paths()

    for path in paths:
        relative = path.as_posix()
        lower_name = path.name.lower()
        suffix = path.suffix.lower()

        if not path.is_file():
            errors.append(f"{relative}: tracked path is not a regular file")
            continue
        if path.stat().st_size > MAX_TRACKED_BYTES:
            errors.append(f"{relative}: tracked file exceeds 10 MiB")
        if suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"{relative}: forbidden database, archive, or credential file")
        if lower_name.startswith("source-manifest") and lower_name.endswith(".jsonl"):
            errors.append(f"{relative}: source manifest must not be tracked")
        if lower_name == "copyrght" and not relative.startswith(SYNTHETIC_ROOT):
            errors.append(f"{relative}: PMGS copyright marker is outside the synthetic fixture")
        if (
            lower_name in {".env", ".dev.vars"} or lower_name.startswith((".env.", ".dev.vars."))
        ) and not lower_name.endswith(".example"):
            errors.append(f"{relative}: environment secret file must not be tracked")
        if any(re.fullmatch(r"JPPM\d+", part, flags=re.IGNORECASE) for part in path.parts):
            errors.append(f"{relative}: PMGS source-package directory must not be tracked")
        if suffix in SOURCE_LIKE_SUFFIXES and not is_allowed_source_like(relative, suffix):
            errors.append(f"{relative}: source-like file is outside the public allowlist")

        errors.extend(content_errors(path, relative))

    return sorted(set(errors)), len(paths)


def main() -> int:
    errors, candidate_count = verify_repository()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"repository-boundary: ok ({candidate_count} tracked or untracked candidate files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
