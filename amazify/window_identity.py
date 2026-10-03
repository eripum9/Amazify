from __future__ import annotations

import ctypes
import logging
import os
import time
import uuid
from ctypes import wintypes
from typing import Any

import psutil

from .config import AMAZIFY_WINDOW_APP_USER_MODEL_ID
from .launcher import _is_exact_amazon_package_executable


LOG = logging.getLogger(__name__)

_IID_IPROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_PKEY_APP_USER_MODEL_ID_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_PKEY_APP_USER_MODEL_ID_PID = 5
_VT_LPWSTR = 31
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = -2147417850


class WindowIdentityError(RuntimeError):
    pass


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "GUID":
        parsed = uuid.UUID(value)
        data4 = (ctypes.c_ubyte * 8)(
            parsed.clock_seq_hi_variant,
            parsed.clock_seq_low,
            *parsed.node.to_bytes(6, "big"),
        )
        return cls(parsed.time_low, parsed.time_mid, parsed.time_hi_version, data4)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", GUID),
        ("pid", wintypes.DWORD),
    ]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("pwszVal", wintypes.LPWSTR),
    ]


def apply_amazify_window_identity(
    process_id: int | None,
    *,
    app_id: str = AMAZIFY_WINDOW_APP_USER_MODEL_ID,
    timeout_seconds: float = 2.5,
) -> int:
    """Apply the taskbar identity only to windows owned by the launched process."""
    if (
        os.name != "nt"
        or not isinstance(process_id, int)
        or isinstance(process_id, bool)
        or process_id <= 0
    ):
        return 0

    try:
        process = psutil.Process(process_id)
        creation_time = process.create_time()
        if not process.is_running():
            return 0
    except (OSError, ValueError, TypeError, psutil.Error) as exc:
        LOG.debug("Unable to verify launched process %s: %s", process_id, exc)
        return 0

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not _is_same_running_process(process, creation_time):
            return 0
        try:
            handles = _find_visible_windows_by_process_id(process_id)
        except WindowIdentityError as exc:
            last_error = exc
            time.sleep(0.05)
            continue

        tagged = 0
        for hwnd in handles:
            if not _is_same_running_process(process, creation_time):
                return 0
            if _window_process_id(hwnd) != process_id:
                continue
            try:
                _set_window_app_user_model_id(hwnd, app_id)
                tagged += 1
            except WindowIdentityError as exc:
                last_error = exc
                LOG.debug("Unable to set AppUserModelID for hwnd=%s: %s", hwnd, exc)
        if tagged:
            return tagged
        time.sleep(0.05)

    if last_error is not None:
        LOG.debug("Window AppUserModelID tagging failed before timeout: %s", last_error)
    return 0


def _is_same_running_process(process: Any, creation_time: float) -> bool:
    try:
        return process.is_running() and process.create_time() == creation_time
    except (OSError, ValueError, TypeError, psutil.Error):
        return False


def _find_visible_windows_by_process_id(process_id: int) -> list[int]:
    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_windows_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def callback(hwnd: int, lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd) and _window_process_id(hwnd) == process_id:
            handles.append(int(hwnd))
        return True

    if not user32.EnumWindows(enum_windows_proc(callback), 0):
        raise WindowIdentityError("EnumWindows failed")
    return handles


def _find_visible_amazon_music_windows() -> list[int]:
    user32 = ctypes.windll.user32
    handles: list[int] = []
    image_cache: dict[int, str] = {}
    enum_windows_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = _window_process_id(hwnd)
        image = image_cache.setdefault(process_id, _process_image_path(process_id))
        if _looks_like_amazon_music_window("", "", image):
            handles.append(int(hwnd))
        return True

    if not user32.EnumWindows(enum_windows_proc(callback), 0):
        raise WindowIdentityError("EnumWindows failed")
    return handles


def _looks_like_amazon_music_window(
    title: str, class_name: str, image_path: str
) -> bool:
    return _is_exact_amazon_package_executable(image_path)


def _process_image_path(pid: int) -> str:
    if pid <= 0:
        return ""
    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _set_window_app_user_model_id(hwnd: int, app_id: str) -> None:
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    hresult = getattr(wintypes, "HRESULT", ctypes.c_long)

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = hresult
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = hresult

    coinit_hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    should_uninitialize = coinit_hr >= 0
    if coinit_hr < 0 and coinit_hr != _RPC_E_CHANGED_MODE:
        raise WindowIdentityError(f"CoInitializeEx failed: 0x{_hresult_hex(coinit_hr)}")

    store = ctypes.c_void_p()
    try:
        iid = GUID.from_string(_IID_IPROPERTY_STORE)
        hr = shell32.SHGetPropertyStoreForWindow(
            wintypes.HWND(hwnd),
            ctypes.byref(iid),
            ctypes.byref(store),
        )
        if hr < 0:
            raise WindowIdentityError(
                f"SHGetPropertyStoreForWindow failed: 0x{_hresult_hex(hr)}"
            )
        if not store.value:
            raise WindowIdentityError(
                "SHGetPropertyStoreForWindow returned a null store"
            )

        property_store = ctypes.cast(
            store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )
        vtable = property_store.contents
        set_value = ctypes.WINFUNCTYPE(
            hresult,
            ctypes.c_void_p,
            ctypes.POINTER(PROPERTYKEY),
            ctypes.POINTER(PROPVARIANT),
        )(vtable[6])
        commit = ctypes.WINFUNCTYPE(hresult, ctypes.c_void_p)(vtable[7])
        pkey = PROPERTYKEY(
            GUID.from_string(_PKEY_APP_USER_MODEL_ID_FMTID),
            _PKEY_APP_USER_MODEL_ID_PID,
        )
        value = PROPVARIANT()
        value.vt = _VT_LPWSTR
        value.pwszVal = app_id

        hr = set_value(store, ctypes.byref(pkey), ctypes.byref(value))
        if hr < 0:
            raise WindowIdentityError(
                f"IPropertyStore.SetValue failed: 0x{_hresult_hex(hr)}"
            )
        hr = commit(store)
        if hr < 0:
            raise WindowIdentityError(
                f"IPropertyStore.Commit failed: 0x{_hresult_hex(hr)}"
            )
    finally:
        if store.value:
            property_store = ctypes.cast(
                store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            )
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(
                property_store.contents[2]
            )
            release(store)
        if should_uninitialize:
            ole32.CoUninitialize()


def _hresult_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08X}"
