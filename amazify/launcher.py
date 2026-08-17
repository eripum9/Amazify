from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_KNOWN_AUMID


LOG = logging.getLogger(__name__)


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LaunchCandidate:
    kind: str
    value: str
    label: str


def discover_launch_candidates(manual_launcher: str | None = None) -> list[LaunchCandidate]:
    candidates: list[LaunchCandidate] = []
    seen: set[tuple[str, str]] = set()

    if manual_launcher:
        candidate = _manual_candidate(manual_launcher)
        candidates.append(candidate)
        seen.add((candidate.kind, candidate.value.lower()))

    for candidate in _start_app_candidates():
        _append_unique(candidates, seen, candidate)

    for candidate in _appx_manifest_candidates():
        _append_unique(candidates, seen, candidate)

    _append_unique(
        candidates,
        seen,
        LaunchCandidate("aumid", DEFAULT_KNOWN_AUMID, "Known Amazon Music Store AUMID"),
    )
    return candidates


def launch_candidate(candidate: LaunchCandidate, devtools_port: int) -> None:
    args = devtools_args(devtools_port)
    LOG.info("Launching %s with DevTools port %s", candidate.label, devtools_port)
    if candidate.kind == "exe":
        subprocess.Popen(
            [candidate.value, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return
    if candidate.kind == "aumid":
        _activate_aumid(candidate.value, " ".join(args))
        return
    raise LaunchError(f"Unsupported launch candidate kind: {candidate.kind}")


def devtools_args(devtools_port: int) -> list[str]:
    return [
        f"--remote-debugging-port={devtools_port}",
        "--remote-allow-origins=*",
    ]


def _append_unique(
    candidates: list[LaunchCandidate],
    seen: set[tuple[str, str]],
    candidate: LaunchCandidate,
) -> None:
    key = (candidate.kind, candidate.value.lower())
    if key not in seen:
        candidates.append(candidate)
        seen.add(key)


def _manual_candidate(value: str) -> LaunchCandidate:
    path = Path(value).expanduser()
    if path.exists() and path.is_file():
        return LaunchCandidate("exe", str(path), f"Manual executable {path.name}")
    return LaunchCandidate("aumid", value, "Manual AUMID")


def _start_app_candidates() -> list[LaunchCandidate]:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-StartApps |
  Where-Object { $_.Name -like '*Amazon Music*' } |
  Select-Object Name, AppID |
  ConvertTo-Json -Depth 4
""".strip()
    data = _run_powershell_json(script)
    items = _ensure_list(data)
    candidates: list[LaunchCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        app_id = str(item.get("AppID", "")).strip()
        name = str(item.get("Name", "Amazon Music")).strip() or "Amazon Music"
        if not _looks_like_amazon_music_start_app(name, app_id):
            continue
        if not app_id:
            continue
        path = Path(app_id)
        if path.exists() and path.is_file():
            candidates.append(LaunchCandidate("exe", str(path), f"{name} executable"))
        else:
            candidates.append(LaunchCandidate("aumid", app_id, f"{name} AUMID"))
    return candidates


def _appx_manifest_candidates() -> list[LaunchCandidate]:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
Get-AppxPackage *AmazonMusic* | ForEach-Object {
  $pkg = $_
  $manifestPath = Join-Path $pkg.InstallLocation 'AppxManifest.xml'
  if (Test-Path $manifestPath) {
    [xml]$manifest = Get-Content $manifestPath
    foreach ($app in $manifest.Package.Applications.Application) {
      $rows += [pscustomobject]@{
        Name = $pkg.Name
        PackageFamilyName = $pkg.PackageFamilyName
        ApplicationId = $app.Id
        AppID = "$($pkg.PackageFamilyName)!$($app.Id)"
      }
    }
  }
}
$rows | ConvertTo-Json -Depth 4
""".strip()
    data = _run_powershell_json(script)
    candidates: list[LaunchCandidate] = []
    for item in _ensure_list(data):
        if not isinstance(item, dict):
            continue
        app_id = str(item.get("AppID", "")).strip()
        name = str(item.get("Name", "Amazon Music")).strip() or "Amazon Music"
        if app_id:
            candidates.append(LaunchCandidate("aumid", app_id, f"{name} package AUMID"))
    return candidates


def _activate_aumid(app_id: str, args: str) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
$code = @"
using System;
using System.Runtime.InteropServices;

namespace AmazifyActivation {{
  [ComImport]
  [Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
  public class ApplicationActivationManager {{}}

  [ComImport]
  [Guid("2e941141-7f97-4756-ba1d-9decde894a3d")]
  [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IApplicationActivationManager {{
    [PreserveSig]
    int ActivateApplication(
      [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
      [MarshalAs(UnmanagedType.LPWStr)] string arguments,
      ActivateOptions options,
      out uint processId);
  }}

  [Flags]
  public enum ActivateOptions {{
    None = 0,
    DesignMode = 1,
    NoErrorUI = 2,
    NoSplashScreen = 4
  }}

  public static class Launcher {{
    public static uint Activate(string appUserModelId, string arguments) {{
      var manager = (IApplicationActivationManager)new ApplicationActivationManager();
      uint processId;
      int hr = manager.ActivateApplication(
        appUserModelId,
        arguments,
        ActivateOptions.None,
        out processId);
      if (hr < 0) {{
        Marshal.ThrowExceptionForHR(hr);
      }}
      return processId;
    }}
  }}
}}
"@
Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
[AmazifyActivation.Launcher]::Activate({_ps_quote(app_id)}, {_ps_quote(args)})
""".strip()
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise LaunchError(result.stderr.strip() or result.stdout.strip())


def _run_powershell_json(script: str) -> object:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        LOG.debug("PowerShell discovery failed: %s", result.stderr.strip())
        return []
    output = result.stdout.strip()
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        LOG.debug("PowerShell returned non-JSON discovery output: %s", output)
        return []


def _ensure_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _looks_like_amazon_music_start_app(name: str, app_id: str) -> bool:
    lowered_name = name.lower()
    lowered_app_id = app_id.lower()
    if "uninstall" in lowered_name or "unins" in lowered_app_id:
        return False
    if "rpc" in lowered_name or "amazonmusicrpc" in lowered_app_id:
        return False
    if lowered_name == "amazon music":
        return True
    return (
        "amazonmusic" in lowered_app_id
        and "amazonmobilellc" in lowered_app_id
        and "!" in app_id
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
