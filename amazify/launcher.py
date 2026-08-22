from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import ctypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes

from .config import DEFAULT_KNOWN_AUMID


LOG = logging.getLogger(__name__)
DEVTOOLS_PORT_RE = re.compile(r"^--remote-debugging-port=(\d+)$")


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


def runtime_launch_candidates(manual_launcher: str | None = None) -> list[LaunchCandidate]:
    """Return the minimal launch set used by the latency-sensitive runtime path."""
    if manual_launcher:
        return [_manual_candidate(manual_launcher)]
    return [
        LaunchCandidate("aumid", DEFAULT_KNOWN_AUMID, "Amazon Music AUMID"),
    ]


def running_amazon_music_devtools_ports() -> list[int]:
    ports: list[int] = []
    try:
        import psutil
    except ImportError:
        return ports

    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            info = process.info
            if not _looks_like_amazon_music_process(
                str(info.get("name") or ""),
                str(info.get("exe") or ""),
            ):
                continue
            for argument in info.get("cmdline") or []:
                match = DEVTOOLS_PORT_RE.match(str(argument))
                if not match:
                    continue
                port = int(match.group(1))
                if 0 < port <= 65535 and port not in ports:
                    ports.append(port)
        except (OSError, ValueError, TypeError, psutil.Error):
            continue
    return ports


def amazon_music_is_running() -> bool:
    try:
        import psutil
    except ImportError:
        return False

    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            info = process.info
            if not _looks_like_amazon_music_process(
                str(info.get("name") or ""),
                str(info.get("exe") or ""),
            ):
                continue
            arguments = [str(item) for item in (info.get("cmdline") or [])]
            if not any(argument.startswith("--type=") for argument in arguments):
                return True
        except (OSError, TypeError, psutil.Error):
            continue
    return False


def focus_amazon_music() -> None:
    _activate_aumid(DEFAULT_KNOWN_AUMID, "")


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
    if os.name == "nt":
        try:
            _activate_aumid_native(app_id, args)
            return
        except (OSError, RuntimeError):
            LOG.debug("Native AUMID activation failed; using PowerShell fallback", exc_info=True)
    _activate_aumid_powershell(app_id, args)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "_GUID":
        parsed = uuid.UUID(value)
        raw = parsed.bytes_le
        return cls.from_buffer_copy(raw)


def _activate_aumid_native(app_id: str, args: str) -> int:
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    clsid = _GUID.from_string("45BA127D-10A8-46EA-8AB7-56EA9078943C")
    iid = _GUID.from_string("2E941141-7F97-4756-BA1D-9DECDE894A3D")
    instance = ctypes.c_void_p()
    coinit_hr = ole32.CoInitializeEx(None, 0x2)
    should_uninitialize = coinit_hr >= 0
    if coinit_hr < 0 and coinit_hr != -2147417850:
        raise RuntimeError(f"CoInitializeEx failed: 0x{coinit_hr & 0xFFFFFFFF:08X}")
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            0x1,
            ctypes.byref(iid),
            ctypes.byref(instance),
        )
        if hr < 0 or not instance.value:
            raise RuntimeError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")
        interface = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        activate = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )(interface.contents[3])
        process_id = wintypes.DWORD()
        hr = activate(instance, app_id, args, 0, ctypes.byref(process_id))
        if hr < 0:
            raise RuntimeError(f"ActivateApplication failed: 0x{hr & 0xFFFFFFFF:08X}")
        return int(process_id.value)
    finally:
        if instance.value:
            interface = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(interface.contents[2])
            release(instance)
        if should_uninitialize:
            ole32.CoUninitialize()


def _activate_aumid_powershell(app_id: str, args: str) -> None:
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


def _looks_like_amazon_music_process(name: str, executable: str) -> bool:
    lowered_name = name.lower()
    lowered_executable = executable.lower()
    if lowered_name != "amazon music.exe":
        return False
    return (
        "amazonmobilellc.amazonmusic_" in lowered_executable
        or lowered_executable.endswith("amazon music.exe")
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
