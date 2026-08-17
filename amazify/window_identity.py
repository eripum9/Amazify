from __future__ import annotations

import ctypes
import json
import logging
import os
import time
import uuid
from ctypes import wintypes
from typing import Any

from .config import AMAZIFY_WINDOW_APP_USER_MODEL_ID


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
    client: Any,
    *,
    app_id: str = AMAZIFY_WINDOW_APP_USER_MODEL_ID,
    timeout_seconds: float = 2.5,
) -> int:
    """Apply the Amazify taskbar identity to the current DevTools target window."""
    if os.name != "nt":
        return 0

    marker = f"AmazifyWindowIdentity-{uuid.uuid4().hex}"
    original_title = _set_document_title_marker(client, marker)
    try:
        tagged = tag_windows_with_exact_title(marker, app_id, timeout_seconds=timeout_seconds)
    finally:
        _restore_document_title(client, original_title)
    if tagged:
        return tagged
    return tag_amazon_music_windows(app_id, timeout_seconds=timeout_seconds)


def tag_windows_with_exact_title(
    title: str,
    app_id: str,
    *,
    timeout_seconds: float = 2.5,
) -> int:
    if os.name != "nt":
        return 0

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        tagged = 0
        for hwnd in _find_visible_windows_by_exact_title(title):
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


def tag_amazon_music_windows(
    app_id: str,
    *,
    timeout_seconds: float = 2.5,
) -> int:
    if os.name != "nt":
        return 0

    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        tagged = 0
        for hwnd in _find_visible_amazon_music_windows():
            try:
                _set_window_app_user_model_id(hwnd, app_id)
                tagged += 1
            except WindowIdentityError as exc:
                last_error = exc
                LOG.debug("Unable to set AppUserModelID for Amazon Music hwnd=%s: %s", hwnd, exc)
        if tagged:
            return tagged
        time.sleep(0.1)

    if last_error is not None:
        LOG.debug("Amazon Music AppUserModelID fallback failed before timeout: %s", last_error)
    return 0


def _set_document_title_marker(client: Any, marker: str) -> str:
    script = f"""
(() => {{
  const marker = {json.dumps(marker)};
  const previous = document.title || "";
  window.__amazifyWindowIdentityPreviousTitle = previous;
  document.title = marker;
  return previous;
}})()
""".strip()
    value = client.evaluate(script)
    return value if isinstance(value, str) else ""


def _restore_document_title(client: Any, original_title: str) -> None:
    script = f"""
(() => {{
  const previous = Object.prototype.hasOwnProperty.call(
    window,
    "__amazifyWindowIdentityPreviousTitle"
  ) ? window.__amazifyWindowIdentityPreviousTitle : {json.dumps(original_title)};
  document.title = previous || "";
  try {{ delete window.__amazifyWindowIdentityPreviousTitle; }} catch (error) {{}}
}})()
""".strip()
    try:
        client.evaluate(script)
    except Exception:
        LOG.debug("Unable to restore Amazon Music title after window tagging", exc_info=True)


def _find_visible_windows_by_exact_title(title: str) -> list[int]:
    user32 = ctypes.windll.user32
    handles: list[int] = []
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value == title:
            handles.append(int(hwnd))
        return True

    if not user32.EnumWindows(enum_windows_proc(callback), 0):
        raise WindowIdentityError("EnumWindows failed")
    return handles


def _find_visible_amazon_music_windows() -> list[int]:
    user32 = ctypes.windll.user32
    handles: list[int] = []
    image_cache: dict[int, str] = {}
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        class_name = _window_class_name(hwnd)
        pid = _window_process_id(hwnd)
        image = image_cache.setdefault(pid, _process_image_path(pid))
        if _looks_like_amazon_music_window(title, class_name, image):
            handles.append(int(hwnd))
        return True

    if not user32.EnumWindows(enum_windows_proc(callback), 0):
        raise WindowIdentityError("EnumWindows failed")
    return handles


def _looks_like_amazon_music_window(title: str, class_name: str, image_path: str) -> bool:
    lowered_title = title.lower()
    lowered_class = class_name.lower()
    lowered_image = image_path.lower()
    combined = f"{lowered_title}\n{lowered_class}\n{lowered_image}"
    if "amazify" in combined or "amazonmusicrpc" in combined:
        return False
    if "windowsapps\\amazonmobilellc.amazonmusic_" in lowered_image:
        return True
    if "amazon music" in lowered_title:
        return True
    return "amazonmusic" in lowered_image and "amazon" in lowered_image


def _window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _window_class_name(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def _window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


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
            raise WindowIdentityError("SHGetPropertyStoreForWindow returned a null store")

        property_store = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
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
            raise WindowIdentityError(f"IPropertyStore.SetValue failed: 0x{_hresult_hex(hr)}")
        hr = commit(store)
        if hr < 0:
            raise WindowIdentityError(f"IPropertyStore.Commit failed: 0x{_hresult_hex(hr)}")
    finally:
        if store.value:
            property_store = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(
                property_store.contents[2]
            )
            release(store)
        if should_uninitialize:
            ole32.CoUninitialize()


def _hresult_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08X}"
