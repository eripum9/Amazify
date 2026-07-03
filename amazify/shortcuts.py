from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


SHORTCUT_BASENAME = "Amazon Music (Amazify)"
SHORTCUT_FILENAME = f"{SHORTCUT_BASENAME}.lnk"


@dataclass(slots=True)
class ShortcutInstallResult:
    created: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def start_menu_shortcut_path() -> Path:
    return _appdata_path() / "Microsoft" / "Windows" / "Start Menu" / "Programs" / SHORTCUT_FILENAME


def desktop_shortcut_path() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    desktop = Path(user_profile) / "Desktop" if user_profile else Path.home() / "Desktop"
    return desktop / SHORTCUT_FILENAME


def taskbar_shortcut_path() -> Path:
    return (
        _appdata_path()
        / "Microsoft"
        / "Internet Explorer"
        / "Quick Launch"
        / "User Pinned"
        / "TaskBar"
        / SHORTCUT_FILENAME
    )


def install_amazify_shortcuts(
    target_exe: Path,
    *,
    start_menu: bool = True,
    desktop: bool = False,
    taskbar: bool = False,
) -> ShortcutInstallResult:
    result = ShortcutInstallResult()
    shortcut_for_taskbar: Path | None = None

    if start_menu:
        shortcut = start_menu_shortcut_path()
        create_amazify_shortcut(shortcut, target_exe)
        result.created.append(shortcut)
        shortcut_for_taskbar = shortcut

    if desktop:
        shortcut = desktop_shortcut_path()
        create_amazify_shortcut(shortcut, target_exe)
        result.created.append(shortcut)
        shortcut_for_taskbar = shortcut_for_taskbar or shortcut

    if taskbar:
        if shortcut_for_taskbar is None:
            shortcut_for_taskbar = start_menu_shortcut_path()
            create_amazify_shortcut(shortcut_for_taskbar, target_exe)
            result.created.append(shortcut_for_taskbar)
        try:
            pin_shortcut_to_taskbar(shortcut_for_taskbar)
        except ShortcutError as exc:
            result.warnings.append(str(exc))

    return result


def remove_amazify_shortcuts() -> ShortcutInstallResult:
    result = ShortcutInstallResult()
    for shortcut in [
        start_menu_shortcut_path(),
        desktop_shortcut_path(),
        taskbar_shortcut_path(),
    ]:
        try:
            if shortcut.exists():
                shortcut.unlink()
                result.removed.append(shortcut)
        except OSError as exc:
            result.warnings.append(f"Unable to remove shortcut {shortcut}: {exc}")
    return result


def create_amazify_shortcut(shortcut_path: Path, target_exe: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    target_exe = target_exe.resolve()
    script = f"""
$ErrorActionPreference = 'Stop'
$shortcutPath = {_ps_quote(str(shortcut_path))}
$targetPath = {_ps_quote(str(target_exe))}
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = 'run'
$shortcut.WorkingDirectory = Split-Path -Parent $targetPath
$shortcut.IconLocation = "$targetPath,0"
$shortcut.Description = 'Launch Amazon Music through Amazify'
$shortcut.Save()
""".strip()
    _run_powershell(script)


def pin_shortcut_to_taskbar(shortcut_path: Path) -> None:
    if not shortcut_path.exists():
        raise ShortcutError(f"Taskbar shortcut does not exist: {shortcut_path}")

    script = f"""
$ErrorActionPreference = 'Stop'
$shortcutPath = {_ps_quote(str(shortcut_path))}
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace((Split-Path -Parent $shortcutPath))
$item = $folder.ParseName((Split-Path -Leaf $shortcutPath))
if ($null -eq $item) {{
  throw "Unable to load shortcut for taskbar pinning: $shortcutPath"
}}
try {{
  $item.InvokeVerb('taskbarpin')
  Start-Sleep -Milliseconds 700
  exit 0
}} catch {{
  $verbs = @($item.Verbs())
  foreach ($verb in $verbs) {{
    $name = ($verb.Name -replace '&', '').Trim()
    if ($name -match 'Pin to taskbar') {{
      $verb.DoIt()
      Start-Sleep -Milliseconds 700
      exit 0
    }}
  }}
  throw "Windows did not expose a taskbar pin action. Pin '{SHORTCUT_BASENAME}' manually from Start if needed."
}}
""".strip()
    _run_powershell(script)


def _appdata_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise ShortcutError("APPDATA is not set")
    return Path(appdata)


def _run_powershell(script: str) -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "PowerShell shortcut command failed"
        raise ShortcutError(detail)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ShortcutError(RuntimeError):
    pass
