from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# Provide a minimal winreg stub so the installer module can be imported on
# platforms where winreg is not available (i.e., non-Windows test environments).
if "winreg" not in sys.modules:
    sys.modules["winreg"] = types.ModuleType("winreg")

# Ensure packaging/ is on sys.path so the installer module can be imported,
# then restore sys.path to avoid polluting the import namespace.
_packaging_dir = str(Path(__file__).parent.parent / "packaging")
_saved_sys_path = sys.path[:]
sys.path.insert(0, _packaging_dir)
try:
    import amazify_installer  # noqa: E402
finally:
    sys.path[:] = _saved_sys_path


class InstallerWindowedDetectionTests(unittest.TestCase):
    def test_is_windowed_false_when_stdout_is_attached(self) -> None:
        with mock.patch.object(sys, "stdout", new=sys.__stdout__):
            self.assertFalse(amazify_installer._is_windowed())

    def test_is_windowed_true_when_stdout_is_none(self) -> None:
        with mock.patch.object(sys, "stdout", new=None):
            self.assertTrue(amazify_installer._is_windowed())


class InstallerMessageBoxTests(unittest.TestCase):
    def _make_ctypes_mock(self) -> mock.MagicMock:
        m = mock.MagicMock()
        # Ensure windll.user32.MessageBoxW is easily reachable.
        return m

    def test_message_box_calls_messagebox_w(self) -> None:
        ctypes_mock = self._make_ctypes_mock()
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}):
            amazify_installer._message_box("Title", "Hello")
        ctypes_mock.windll.user32.MessageBoxW.assert_called_once()

    def test_message_box_passes_title_and_text(self) -> None:
        ctypes_mock = self._make_ctypes_mock()
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}):
            amazify_installer._message_box("My Title", "My Message")
        args = ctypes_mock.windll.user32.MessageBoxW.call_args.args
        self.assertEqual(args[1], "My Message")
        self.assertEqual(args[2], "My Title")

    def test_message_box_uses_information_icon_by_default(self) -> None:
        ctypes_mock = self._make_ctypes_mock()
        MB_ICONINFORMATION = 0x40
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}):
            amazify_installer._message_box("T", "M")
        flags = ctypes_mock.windll.user32.MessageBoxW.call_args.args[3]
        self.assertTrue(flags & MB_ICONINFORMATION)

    def test_message_box_uses_error_icon_when_requested(self) -> None:
        ctypes_mock = self._make_ctypes_mock()
        MB_ICONERROR = 0x10
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}):
            amazify_installer._message_box("T", "M", error=True)
        flags = ctypes_mock.windll.user32.MessageBoxW.call_args.args[3]
        self.assertTrue(flags & MB_ICONERROR)

    def test_message_box_survives_ctypes_exception(self) -> None:
        ctypes_mock = self._make_ctypes_mock()
        ctypes_mock.windll.user32.MessageBoxW.side_effect = OSError("test error")
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}):
            # Must not raise.
            amazify_installer._message_box("T", "M")


if __name__ == "__main__":
    unittest.main()
