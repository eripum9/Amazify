from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = BUILD / "spec"
ICON = ROOT / "packaging" / "assets" / "logo.ico"
PYINSTALLER = [sys.executable, "-m", "PyInstaller"]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def remove_file(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> int:
    shutil.rmtree(BUILD, ignore_errors=True)
    DIST.mkdir(exist_ok=True)
    SPEC.mkdir(parents=True, exist_ok=True)
    remove_file(DIST / "amazify.exe")
    remove_file(DIST / "AmazifySetup.exe")
    if not ICON.exists():
        raise SystemExit(f"Expected icon missing: {ICON}")

    run(
        [
            *PYINSTALLER,
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--icon",
            str(ICON),
            "--name",
            "amazify",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "amazify"),
            "--specpath",
            str(SPEC),
            str(ROOT / "packaging" / "amazify_cli.py"),
        ]
    )

    amazify_exe = DIST / "amazify.exe"
    if not amazify_exe.exists():
        raise SystemExit(f"Expected build output missing: {amazify_exe}")

    run(
        [
            *PYINSTALLER,
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--icon",
            str(ICON),
            "--name",
            "AmazifySetup",
            "--add-binary",
            f"{amazify_exe}{os.pathsep}.",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "installer"),
            "--specpath",
            str(SPEC),
            str(ROOT / "packaging" / "amazify_installer.py"),
        ]
    )

    setup_exe = DIST / "AmazifySetup.exe"
    if not setup_exe.exists():
        raise SystemExit(f"Expected installer output missing: {setup_exe}")

    print("")
    print("Built:")
    print(f"- {amazify_exe}")
    print(f"- {setup_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
