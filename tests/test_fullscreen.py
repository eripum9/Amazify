import ctypes
import json
from ctypes import wintypes
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from amazify.fullscreen import (
    SW_SHOWMAXIMIZED, SW_SHOWNOACTIVATE, SWP_FRAMECHANGED, SWP_NOACTIVATE,
    SWP_NOZORDER, FullscreenController, WindowPlacement, WindowsDesktop,
)
from amazify.native_bridge import NativeBindingBridge
from amazify.plugin_manager import PluginError


def desktop():
    api = Mock()
    api.candidates.return_value = [42]
    api.pid.return_value = 100
    api.capture.return_value = {"hwnd": 42, "pid": 100, "style": 123}
    return api


def test_frame_is_captured_once_and_restored_on_exit_or_close():
    api = desktop()
    controller = FullscreenController(api)
    assert controller.set_active(True)["active"]
    assert controller.set_active(True)["active"]
    api.capture.assert_called_once_with(42)
    api.enter.assert_called_once_with(api.capture.return_value)
    assert controller.set_active(False) == {"ok": True, "active": False}
    controller.close()
    api.restore.assert_called_once_with(api.capture.return_value)


@pytest.mark.parametrize("windows", [[], [42, 43]])
def test_ambiguous_or_missing_window_is_not_changed(windows):
    api = desktop()
    api.candidates.return_value = windows
    assert not FullscreenController(api).set_active(True)["ok"]
    api.enter.assert_not_called()


def test_recycled_window_handle_is_never_restored():
    api = desktop()
    controller = FullscreenController(api)
    controller.set_active(True)
    api.pid.return_value = 200
    controller.close()
    api.restore.assert_not_called()


def test_partial_entry_failure_rolls_back_frame():
    api = desktop()
    api.enter.side_effect = OSError("failed resize")
    controller = FullscreenController(api)
    with pytest.raises(OSError):
        controller.set_active(True)
    api.restore.assert_called_once()
    assert controller.saved is None


def restore_desktop(show_cmd):
    api = WindowsDesktop.__new__(WindowsDesktop)
    api.api = Mock()
    api._style = Mock()
    placement = WindowPlacement(length=ctypes.sizeof(WindowPlacement), flags=2, showCmd=show_cmd)
    placement.rcNormalPosition = wintypes.RECT(100, 120, 1100, 920)
    state = {"hwnd": 42, "pid": 100, "style": 123, "exstyle": 456,
             "placement": placement, "rect": wintypes.RECT(-8, -8, 1928, 1048)}
    return api, state


@pytest.mark.parametrize("show_cmd", [1, SW_SHOWMAXIMIZED])
def test_native_restore_recalculates_frame_after_show_state_and_normalizes_maximized_view(show_cmd):
    api, state = restore_desktop(show_cmd)
    placements = []
    events = []

    def place(hwnd, pointer):
        placements.append(WindowPlacement.from_buffer_copy(pointer._obj))
        events.append("placement")
        return True

    def resize(*args):
        events.append("frame")
        return True

    api.api.SetWindowPlacement.side_effect = place
    api.api.SetWindowPos.side_effect = resize
    original = bytes(state["placement"])
    api.restore(state)
    api._style.assert_has_calls([call(42, -16, 123), call(42, -20, 456)])
    assert events[-1] == "frame"
    assert placements[-1].showCmd == show_cmd
    assert bytes(state["placement"]) == original
    if show_cmd == SW_SHOWMAXIMIZED:
        assert events == ["placement", "placement", "frame"]
        assert placements[0].showCmd == SW_SHOWNOACTIVATE
        assert placements[0].flags == 0
        assert bytes(placements[0].rcNormalPosition) == bytes(state["placement"].rcNormalPosition)
    else:
        assert events == ["placement", "frame"]
    api.api.SetWindowPos.assert_called_once_with(
        42, None, -8, -8, 1936, 1056, SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE,
    )


@pytest.mark.parametrize("failure", ["normalize", "placement", "frame"])
def test_native_restore_reports_failed_window_operations(failure):
    api, state = restore_desktop(SW_SHOWMAXIMIZED)
    api.api.SetWindowPlacement.side_effect = [failure != "normalize", failure != "placement"]
    api.api.SetWindowPos.return_value = failure != "frame"
    with pytest.raises(OSError):
        api.restore(state)
    if failure != "frame":
        api.api.SetWindowPos.assert_not_called()


def test_failed_restore_retains_saved_frame_for_retry():
    api = desktop()
    controller = FullscreenController(api)
    controller.set_active(True)
    api.restore.side_effect = [OSError("failed restore"), None]
    with pytest.raises(OSError):
        controller.close()
    assert controller.saved is api.capture.return_value
    controller.close()
    assert controller.saved is None


def test_signal_normal_transport_anchors_are_supported_by_embedded_chromium():
    css = (Path(__file__).parents[1] / "sample_plugins" / "amazify.theme.signal-studio" / "theme.css").read_text(encoding="utf-8")
    selector = "body.amazify-signal-studio:not(.amazify-true-big-mode-active) #transportContainer:not(.childViewShowing) #transport {"
    rule = css.split(selector, 1)[1].split("}", 1)[0]
    for edge in ("top", "right", "bottom", "left"):
        assert f"{edge}: 0 !important;" in rule
    assert "inset:" not in rule


@pytest.mark.parametrize("exit_succeeds", [True, False])
def test_live_qa_failure_after_f11_still_exits_browser_before_cleanup_and_reports_restoration(monkeypatch, tmp_path, exit_succeeds):
    from scripts import verify_fullscreen_live as qa

    api, state = restore_desktop(1)
    api.candidates = Mock(return_value=[42])
    api.capture = Mock(return_value=state)
    events = []
    api.restore = Mock(side_effect=lambda saved: events.append("frame"))
    client = Mock()
    active = False
    metrics = {"viewport": {}, "transport": {}, "controls": {}, "transportClass": "hasTrackLoaded"}

    def evaluate(expression):
        nonlocal active
        if expression == qa.METRICS:
            return json.dumps({**metrics, "fullscreen": active})
        if expression == qa.EXIT_FULLSCREEN:
            events.append("exit")
            if exit_succeeds:
                active = False
        elif expression == "cleanup":
            events.append("cleanup")
        return None

    def enter_and_fail(_client):
        nonlocal active
        active = True
        events.append("enter")
        raise RuntimeError("deliberate failure after F11")

    client.evaluate.side_effect = evaluate
    client.call.return_value = {"data": ""}
    bridge = Mock()
    bridge.close.side_effect = lambda: events.append("bridge-close")
    monkeypatch.setattr(qa, "WindowsDesktop", lambda: api)
    monkeypatch.setattr(qa, "DevToolsHttp", Mock())
    monkeypatch.setattr(qa, "DevToolsClient", lambda target: client)
    monkeypatch.setattr(qa, "PluginManager", Mock())
    monkeypatch.setattr(qa, "NativeBindingBridge", lambda c, manager: bridge)
    monkeypatch.setattr(qa, "build_runtime_script", lambda **kwargs: "runtime")
    monkeypatch.setattr(qa, "build_cleanup_script", lambda: "cleanup")
    monkeypatch.setattr(qa, "pump_for", lambda c, seconds: events.append("pump"))
    monkeypatch.setattr(qa, "f11", enter_and_fail)
    monkeypatch.setattr(qa.sys, "argv", ["qa", "--port", "12345", "--output", str(tmp_path)])
    with pytest.raises(RuntimeError, match="deliberate failure after F11"):
        qa.main()
    assert events[events.index("enter"):] == ["enter", "exit", "pump", "cleanup", "pump", "bridge-close", "frame", "pump"]
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["settingsRestored"] is True
    assert report["restored"]["frame"] == report["originalFrame"]
    assert report["restored"]["fullscreen"] is not exit_succeeds
    assert bool(report["failures"]) is not exit_succeeds
    client.close.assert_called_once()


def test_native_command_requires_boolean_and_browser_fullscreen_then_restores_on_close():
    client = Mock()
    bridge = NativeBindingBridge(client, Mock())
    bridge.fullscreen = Mock()
    client.evaluate.return_value = False
    with pytest.raises(ValueError):
        bridge._handle_command("window.fullscreen.set", {"active": "yes"})
    with pytest.raises(PluginError):
        bridge._handle_command("window.fullscreen.set", {"active": True})
    bridge.fullscreen.set_active.assert_not_called()
    client.evaluate.return_value = True
    bridge._handle_command("window.fullscreen.set", {"active": True})
    bridge.fullscreen.set_active.assert_called_once_with(True)
    bridge.close()
    bridge.close()
    bridge.fullscreen.close.assert_called_once()
    with pytest.raises(PluginError):
        bridge._handle_command("window.fullscreen.set", {"active": True})
