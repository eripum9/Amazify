from __future__ import annotations

import ctypes
import json
import logging
import math
import ntpath
import os
import re
import subprocess
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import DEFAULT_KNOWN_AUMID

LOG = logging.getLogger(__name__)
DEVTOOLS_PORT_RE = re.compile(r"^--remote-debugging-port=(\d+)$")
AMAZON_PACKAGE_NAME = "AmazonMobileLLC.AmazonMusic"
AMAZON_PACKAGE_PUBLISHER_ID = "kc6t79cpj4tp0"
AMAZON_EXECUTABLE_NAMES = frozenset({"amazon music.exe", "amazonmusic.exe"})
AMAZON_PACKAGE_DIRECTORY_RE = re.compile(
    rf"^{re.escape(AMAZON_PACKAGE_NAME)}_"
    r"(?P<version>\d{1,5}(?:\.\d{1,5}){3})_"
    r"(?:x86|x64|arm|arm64|neutral)_"
    rf"[A-Za-z0-9.-]{{0,30}}_{AMAZON_PACKAGE_PUBLISHER_ID}$",
    re.IGNORECASE,
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
EXPECTED_LISTENER_TTL_SECONDS = 60.0
_EXPECTED_LISTENERS_LOCK = threading.RLock()


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ExpectedListenerIdentity:
    creation_time: float
    expires_at: float


_EXPECTED_LISTENERS: dict[int, dict[int, _ExpectedListenerIdentity]] = {}


@dataclass(frozen=True, slots=True)
class LaunchCandidate:
    kind: str
    value: str
    label: str


def discover_launch_candidates(
    manual_launcher: str | None = None,
) -> list[LaunchCandidate]:
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


def runtime_launch_candidates(
    manual_launcher: str | None = None,
) -> list[LaunchCandidate]:
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


def launch_candidate(candidate: LaunchCandidate, devtools_port: int) -> int | None:
    args = devtools_args(devtools_port)
    LOG.info("Launching %s with DevTools port %s", candidate.label, devtools_port)
    if candidate.kind == "exe":
        process = subprocess.Popen(
            [candidate.value, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        process_id = _positive_process_id(getattr(process, "pid", None))
        _remember_expected_listener(devtools_port, process_id)
        return process_id
    if candidate.kind == "aumid":
        process_id = _positive_process_id(
            _activate_aumid(candidate.value, " ".join(args))
        )
        _remember_expected_listener(devtools_port, process_id)
        return process_id
    raise LaunchError(f"Unsupported launch candidate kind: {candidate.kind}")


def devtools_args(devtools_port: int) -> list[str]:
    return [f"--remote-debugging-port={devtools_port}"]


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


def _activate_aumid(app_id: str, args: str) -> int | None:
    if os.name == "nt":
        try:
            return _activate_aumid_native(app_id, args)
        except (OSError, RuntimeError):
            LOG.debug(
                "Native AUMID activation failed; using PowerShell fallback",
                exc_info=True,
            )
    return _activate_aumid_powershell(app_id, args)


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
        interface = ctypes.cast(
            instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )
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
            interface = ctypes.cast(
                instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            )
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(
                interface.contents[2]
            )
            release(instance)
        if should_uninitialize:
            ole32.CoUninitialize()


def _activate_aumid_powershell(app_id: str, args: str) -> int | None:
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
    for line in reversed(result.stdout.splitlines()):
        process_id = _positive_process_id(line.strip())
        if process_id is not None:
            return process_id
    return None


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
    lowered_name = name.casefold()
    if lowered_name not in AMAZON_EXECUTABLE_NAMES:
        return False
    return _is_exact_amazon_package_executable(executable)


def validate_devtools_listener(port: int) -> None:
    """Fail unless the selected loopback listener belongs to Amazon Music."""
    try:
        selected_port = int(port)
    except (TypeError, ValueError) as exc:
        raise LaunchError("DevTools listener port is invalid") from exc
    if not 0 < selected_port <= 65535:
        raise LaunchError("DevTools listener port is invalid")

    try:
        import psutil
    except ImportError as exc:
        raise LaunchError(
            "psutil is required to verify the DevTools listener owner"
        ) from exc

    try:
        connections = psutil.net_connections(kind="tcp")
    except (OSError, psutil.Error) as exc:
        raise LaunchError(
            "Windows could not verify the Amazon Music DevTools listener owner"
        ) from exc

    listener_pids: set[int] = set()
    for connection in connections:
        if str(getattr(connection, "status", "")).upper() != "LISTEN":
            continue
        host, connection_port = _connection_address(getattr(connection, "laddr", None))
        if connection_port != selected_port:
            continue
        if host not in LOOPBACK_HOSTS:
            raise LaunchError(
                f"DevTools port {selected_port} is listening on a non-loopback interface"
            )
        process_id = _positive_process_id(getattr(connection, "pid", None))
        if process_id is None:
            raise LaunchError(
                f"Windows could not identify the owner of DevTools port {selected_port}"
            )
        listener_pids.add(process_id)

    if not listener_pids:
        raise LaunchError(
            f"Windows could not find the listener owner for DevTools port {selected_port}"
        )

    with _EXPECTED_LISTENERS_LOCK:
        now = time.monotonic()
        expected = _EXPECTED_LISTENERS.get(selected_port, {})
        expected_identities = {
            process_id: identity
            for process_id, identity in expected.items()
            if identity.expires_at >= now
        }
        if expected:
            if expected_identities:
                _EXPECTED_LISTENERS[selected_port] = expected_identities
            else:
                _EXPECTED_LISTENERS.pop(selected_port, None)

    for process_id in listener_pids:
        if not _trusted_listener_process(psutil, process_id, expected_identities):
            raise LaunchError(
                f"DevTools port {selected_port} is owned by a non-Amazon process"
            )


def _trusted_listener_process(
    psutil_module: Any,
    process_id: int,
    expected_identities: dict[int, _ExpectedListenerIdentity],
) -> bool:
    try:
        process = psutil_module.Process(process_id)
        chain = [process, *process.parents()[:6]]
    except (OSError, psutil_module.Error):
        return False

    for item in chain:
        try:
            item_pid = _positive_process_id(getattr(item, "pid", None))
            executable = str(item.exe() or "")
        except (OSError, psutil_module.Error):
            executable = ""
            item_pid = _positive_process_id(getattr(item, "pid", None))
        if item_pid is not None:
            expected_identity = expected_identities.get(item_pid)
            if expected_identity is not None:
                creation_time = _process_creation_time(psutil_module, item)
                if creation_time == expected_identity.creation_time:
                    return True
        if _is_exact_amazon_package_executable(executable):
            return True
    return False


def _is_exact_amazon_package_executable(path: str) -> bool:
    if not path or not ntpath.isabs(path):
        return False
    normalized = ntpath.normpath(path.replace("/", "\\"))
    if ntpath.basename(normalized).casefold() not in AMAZON_EXECUTABLE_NAMES:
        return False
    package_directory = ntpath.dirname(normalized)
    match = AMAZON_PACKAGE_DIRECTORY_RE.fullmatch(
        ntpath.basename(package_directory)
    )
    if match is None:
        return False
    if any(int(component) > 65535 for component in match["version"].split(".")):
        return False
    windows_apps_root = _canonical_windows_path(ntpath.dirname(package_directory))
    protected_roots = {
        _canonical_windows_path(root)
        for root in _protected_windows_apps_roots()
        if ntpath.isabs(root)
    }
    return windows_apps_root in protected_roots


def _protected_windows_apps_roots() -> frozenset[str]:
    try:
        import winreg
    except ImportError:
        return frozenset()

    roots: set[str] = set()
    access_modes = [winreg.KEY_READ]
    wow64_access = getattr(winreg, "KEY_WOW64_64KEY", 0)
    if wow64_access:
        access_modes.insert(0, winreg.KEY_READ | wow64_access)
    for access in access_modes:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion",
                access=access,
            ) as key:
                program_files, _ = winreg.QueryValueEx(key, "ProgramFilesDir")
        except OSError:
            continue
        if isinstance(program_files, str) and ntpath.isabs(program_files):
            roots.add(ntpath.join(program_files, "WindowsApps"))
    return frozenset(roots)


def _canonical_windows_path(path: str) -> str:
    return ntpath.normcase(ntpath.abspath(ntpath.normpath(path)))


def _connection_address(address: object) -> tuple[str, int]:
    if address is None:
        return "", 0
    host = getattr(address, "ip", None)
    port = getattr(address, "port", None)
    if host is None and isinstance(address, (tuple, list)) and len(address) >= 2:
        host, port = address[0], address[1]
    try:
        return str(host or "").lower(), int(port or 0)
    except (TypeError, ValueError):
        return "", 0


def _positive_process_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        process_id = int(value)
    except (TypeError, ValueError):
        return None
    return process_id if process_id > 0 else None


def _remember_expected_listener(port: int, process_id: int | None) -> None:
    if process_id is None:
        return
    try:
        import psutil
    except ImportError:
        return
    try:
        process = psutil.Process(process_id)
    except (OSError, psutil.Error):
        return
    creation_time = _process_creation_time(psutil, process)
    if creation_time is None:
        return
    with _EXPECTED_LISTENERS_LOCK:
        _EXPECTED_LISTENERS.setdefault(int(port), {})[process_id] = (
            _ExpectedListenerIdentity(
                creation_time=creation_time,
                expires_at=time.monotonic() + EXPECTED_LISTENER_TTL_SECONDS,
            )
        )


def _process_creation_time(psutil_module: Any, process: Any) -> float | None:
    try:
        creation_time = float(process.create_time())
    except (OSError, TypeError, ValueError, psutil_module.Error):
        return None
    if creation_time <= 0 or not math.isfinite(creation_time):
        return None
    return creation_time


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
