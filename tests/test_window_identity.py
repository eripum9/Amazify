from __future__ import annotations

import ctypes
import types
import unittest
from unittest import mock

import psutil

from amazify.window_identity import (
    WindowIdentityError,
    _find_visible_windows_by_process_id,
    _looks_like_amazon_music_window,
    apply_amazify_window_identity,
)


class WindowIdentityTests(unittest.TestCase):
    def _valid_process(self) -> mock.Mock:
        process = mock.Mock()
        process.create_time.return_value = 123.0
        process.is_running.return_value = True
        return process

    def test_invalid_pid_fails_closed(self) -> None:
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process") as create_process,
        ):
            for process_id in (None, 0, -1, True):
                self.assertEqual(apply_amazify_window_identity(process_id), 0)
        create_process.assert_not_called()

    def test_unrelated_same_title_and_other_amazon_pid_are_not_selected(self) -> None:
        user32 = mock.Mock()
        user32.IsWindowVisible.return_value = True
        user32.EnumWindows.side_effect = lambda callback, _: (
            callback(101, 0),
            callback(202, 0),
            callback(303, 0),
            True,
        )[-1]
        hwnd_pids = {101: 41, 202: 42, 303: 43}

        with (
            mock.patch.object(
                ctypes, "WINFUNCTYPE", side_effect=lambda *_: lambda fn: fn, create=True
            ),
            mock.patch.object(
                ctypes, "windll", types.SimpleNamespace(user32=user32), create=True
            ),
            mock.patch(
                "amazify.window_identity._window_process_id", side_effect=hwnd_pids.get
            ),
        ):
            selected = _find_visible_windows_by_process_id(42)

        self.assertEqual(selected, [202])

    def test_target_selection_does_not_depend_on_window_title(self) -> None:
        process = self._valid_process()
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process", return_value=process),
            mock.patch(
                "amazify.window_identity._find_visible_windows_by_process_id",
                return_value=[123],
            ),
            mock.patch("amazify.window_identity._window_process_id", return_value=42),
            mock.patch(
                "amazify.window_identity._set_window_app_user_model_id"
            ) as setter,
        ):
            tagged = apply_amazify_window_identity(42)

        self.assertEqual(tagged, 1)
        setter.assert_called_once_with(123, "Amazify.AmazonMusic")

    def test_pid_reuse_before_mutation_is_not_tagged(self) -> None:
        process = self._valid_process()
        process.create_time.side_effect = [123.0, 123.0, 456.0]
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process", return_value=process),
            mock.patch(
                "amazify.window_identity._find_visible_windows_by_process_id",
                return_value=[123],
            ),
            mock.patch("amazify.window_identity._window_process_id", return_value=42),
            mock.patch(
                "amazify.window_identity._set_window_app_user_model_id"
            ) as setter,
        ):
            tagged = apply_amazify_window_identity(42)

        self.assertEqual(tagged, 0)
        setter.assert_not_called()

    def test_missing_or_inaccessible_process_fails_closed(self) -> None:
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process", side_effect=psutil.AccessDenied(42)),
        ):
            self.assertEqual(apply_amazify_window_identity(42), 0)

    def test_changed_window_owner_is_not_tagged(self) -> None:
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process", return_value=self._valid_process()),
            mock.patch(
                "amazify.window_identity._find_visible_windows_by_process_id",
                return_value=[123],
            ),
            mock.patch("amazify.window_identity._window_process_id", return_value=43),
            mock.patch(
                "amazify.window_identity.time.monotonic", side_effect=[0.0, 0.0, 1.0]
            ),
            mock.patch("amazify.window_identity.time.sleep"),
            mock.patch(
                "amazify.window_identity._set_window_app_user_model_id"
            ) as setter,
        ):
            self.assertEqual(apply_amazify_window_identity(42, timeout_seconds=0.1), 0)
        setter.assert_not_called()

    def test_window_enumeration_error_times_out_without_mutation(self) -> None:
        process = self._valid_process()
        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch("psutil.Process", return_value=process),
            mock.patch(
                "amazify.window_identity._find_visible_windows_by_process_id",
                side_effect=WindowIdentityError("enumeration failed"),
            ),
            mock.patch(
                "amazify.window_identity.time.monotonic", side_effect=[0.0, 0.0, 1.0]
            ),
            mock.patch("amazify.window_identity.time.sleep"),
            mock.patch(
                "amazify.window_identity._set_window_app_user_model_id"
            ) as setter,
        ):
            tagged = apply_amazify_window_identity(42, timeout_seconds=0.1)

        self.assertEqual(tagged, 0)
        setter.assert_not_called()

    def test_non_windows_skips_process_lookup(self) -> None:
        with (
            mock.patch("amazify.window_identity.os.name", "posix"),
            mock.patch("psutil.Process") as create_process,
        ):
            self.assertEqual(apply_amazify_window_identity(42), 0)
        create_process.assert_not_called()

    def test_fullscreen_executable_match_does_not_use_title_or_rpc_name(self) -> None:
        with mock.patch(
            "amazify.window_identity._is_exact_amazon_package_executable",
            side_effect=lambda path: path.endswith("AmazonMusic.exe"),
        ):
            self.assertTrue(
                _looks_like_amazon_music_window(
                    "OperaGX Amazon Music", "BrowserWindow", "C:\\Apps\\AmazonMusic.exe"
                )
            )
            self.assertFalse(
                _looks_like_amazon_music_window(
                    "Amazon Music",
                    "ApplicationFrameWindow",
                    "C:\\Apps\\AmazonMusicRPC.exe",
                )
            )


if __name__ == "__main__":
    unittest.main()
