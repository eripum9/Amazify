from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def matched_version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not read version from {path.relative_to(ROOT)}")
    return match.group(1)


def main() -> int:
    expected = os.environ.get("AMAZIFY_CANDIDATE_VERSION", "").strip()
    selected_ref = os.environ.get("AMAZIFY_CANDIDATE_REF", "").strip()
    if not VERSION_RE.fullmatch(expected):
        raise SystemExit(
            "Candidate version must use major.minor.patch without a v prefix"
        )
    if selected_ref != "refs/heads/main":
        raise SystemExit("Windows candidates can only be built from main")

    head = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    if head != remote:
        raise SystemExit(f"Selected commit {head} is not current main {remote}")

    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = str(tomllib.load(handle)["project"]["version"])
    versions = {
        "pyproject.toml": project_version,
        "amazify/__init__.py": matched_version(
            ROOT / "amazify" / "__init__.py",
            r'^__version__\s*=\s*"([^"]+)"',
        ),
        "packaging/Amazify.iss": matched_version(
            ROOT / "packaging" / "Amazify.iss",
            r'^#define\s+AppVersion\s+"([^"]+)"',
        ),
        "packaging/amazify_installer.py": matched_version(
            ROOT / "packaging" / "amazify_installer.py",
            r'^APP_VERSION\s*=\s*"([^"]+)"',
        ),
    }
    mismatches = {
        name: version for name, version in versions.items() if version != expected
    }
    if mismatches:
        details = ", ".join(f"{name}={version}" for name, version in mismatches.items())
        raise SystemExit(f"Candidate version {expected} does not match {details}")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"sha={head}\n")
            output.write(f"version={expected}\n")
    else:
        print(f"Validated Amazify {expected} at {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
