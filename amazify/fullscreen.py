"""Reversible borderless fullscreen for the single Amazon Music desktop window."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import PureWindowsPath
from typing import Any

from . import window_identity

WS_FRAME = 0x00CF0000  # WS_OVERLAPPEDWINDOW
EX_FRAME = 0x00020301  # modal, window/client/static edge
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSENDCHANGING = 0x0400
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4


class WindowPlacement(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT)]


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class WindowsDesktop:
    def __init__(self) -> None:
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        api = self.api
        self.get_style = getattr(api, "GetWindowLongPtrW", api.GetWindowLongW)
        self.set_style = getattr(api, "SetWindowLongPtrW", api.SetWindowLongW)
        self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style.restype = ctypes.c_ssize_t
        self.set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.set_style.restype = ctypes.c_ssize_t
        api.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WindowPlacement)]
        api.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WindowPlacement)]
        api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
        api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        api.MonitorFromWindow.restype = wintypes.HANDLE
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]

    def candidates(self) -> list[int]:
        # A title alone is not sufficient. Never touch RPC or other applications,
        # and fail closed if several Amazon windows make the target ambiguous.
        return [hwnd for hwnd in window_identity._find_visible_amazon_music_windows()
                if PureWindowsPath(window_identity._process_image_path(
                    window_identity._window_process_id(hwnd))).name.lower()
                in {"amazon music.exe", "amazonmusic.exe"}]

    def pid(self, hwnd: int) -> int:
        return window_identity._window_process_id(hwnd)

    def capture(self, hwnd: int) -> dict[str, Any]:
        placement = WindowPlacement(length=ctypes.sizeof(WindowPlacement))
        rect = wintypes.RECT()
        if not self.api.GetWindowPlacement(hwnd, ctypes.byref(placement)) or not self.api.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError("Could not read Amazon Music window placement")
        return dict(hwnd=hwnd, pid=self.pid(hwnd), style=self.get_style(hwnd, -16),
                    exstyle=self.get_style(hwnd, -20), placement=placement, rect=rect)

    def _style(self, hwnd: int, index: int, value: int) -> None:
        ctypes.set_last_error(0)
        result = self.set_style(hwnd, index, value)
        if result == 0 and ctypes.get_last_error():
            raise OSError("Could not change Amazon Music window frame")

    def enter(self, state: dict[str, Any]) -> None:
        hwnd = state["hwnd"]
        info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
        monitor = self.api.MonitorFromWindow(hwnd, 2)
        if not self.api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise OSError("Could not locate Amazon Music monitor")
        self._style(hwnd, -16, state["style"] & ~WS_FRAME)
        self._style(hwnd, -20, state["exstyle"] & ~EX_FRAME)
        r = info.rcMonitor
        # Amazon clamps normal window changes to the work area (excluding the
        # taskbar). The borderless frame must instead cover the whole monitor.
        if not self.api.SetWindowPos(hwnd, None, r.left, r.top, r.right-r.left, r.bottom-r.top,
                                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING):
            raise OSError("Could not enter Amazon Music fullscreen")

    def restore(self, state: dict[str, Any]) -> None:
        hwnd = state["hwnd"]
        self._style(hwnd, -16, state["style"])
        self._style(hwnd, -20, state["exstyle"])
        if state["placement"].showCmd == SW_SHOWMAXIMIZED:
            # The host remains logically maximized in borderless fullscreen.
            # A same-state maximize restores the frame but not Chromium's view.
            # Normalize without activation so the final maximize sends WM_SIZE.
            normal = WindowPlacement.from_buffer_copy(state["placement"])
            normal.showCmd = SW_SHOWNOACTIVATE
            normal.flags = 0
            if not self.api.SetWindowPlacement(hwnd, ctypes.byref(normal)):
                raise OSError("Could not reset Amazon Music maximized placement")
        if not self.api.SetWindowPlacement(hwnd, ctypes.byref(state["placement"])):
            raise OSError("Could not restore Amazon Music window placement")
        r = state["rect"]
        # Recalculate the client frame after restoring the show state. Otherwise
        # a maximized Chromium host can retain its fullscreen renderer viewport.
        if not self.api.SetWindowPos(hwnd, None, r.left, r.top, r.right-r.left, r.bottom-r.top,
                                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE):
            raise OSError("Could not restore Amazon Music window frame")


class FullscreenController:
    def __init__(self, desktop: Any = None) -> None:
        self.desktop = desktop
        self.saved: dict[str, Any] | None = None

    def set_active(self, active: bool) -> dict[str, Any]:
        if type(active) is not bool:
            raise ValueError("Fullscreen active must be a boolean")
        if not active:
            self.close()
            return {"ok": True, "active": False}
        if self.desktop is None:
            if os.name != "nt":
                return {"ok": False, "error": "Desktop fullscreen requires Windows"}
            self.desktop = WindowsDesktop()
        if self.saved is not None:
            if self.desktop.pid(self.saved["hwnd"]) == self.saved["pid"]:
                return {"ok": True, "active": True}
            self.saved = None
        candidates = self.desktop.candidates()
        if len(candidates) != 1:
            return {"ok": False, "error": "Could not identify a unique Amazon Music window"}
        state: dict[str, Any] = self.desktop.capture(candidates[0])
        self.saved = state
        try:
            self.desktop.enter(state)
        except OSError:
            self.close()
            raise
        return {"ok": True, "active": True}

    def close(self) -> None:
        if self.saved is None:
            return
        state = self.saved
        # A recycled HWND must never restore the frame of another application.
        if self.desktop.pid(state["hwnd"]) != state["pid"]:
            self.saved = None
            return
        self.desktop.restore(state)
        self.saved = None
