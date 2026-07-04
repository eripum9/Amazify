from __future__ import annotations

import unittest
from unittest import mock

from amazify.window_identity import apply_amazify_window_identity
from amazify.window_identity import _looks_like_amazon_music_window


class FakeDevToolsClient:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def evaluate(self, script: str) -> object:
        self.scripts.append(script)
        if "return previous;" in script:
            return "Amazon Music"
        return None


class WindowIdentityTests(unittest.TestCase):
    def test_apply_identity_marks_exact_target_title_and_restores_it(self) -> None:
        client = FakeDevToolsClient()

        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch(
                "amazify.window_identity.tag_windows_with_exact_title",
                return_value=1,
            ) as tag_windows,
        ):
            tagged = apply_amazify_window_identity(
                client,
                app_id="Amazify.Test",
                timeout_seconds=0.25,
            )

        self.assertEqual(tagged, 1)
        tag_windows.assert_called_once()
        marker, app_id = tag_windows.call_args.args
        self.assertTrue(marker.startswith("AmazifyWindowIdentity-"))
        self.assertEqual(app_id, "Amazify.Test")
        self.assertEqual(tag_windows.call_args.kwargs["timeout_seconds"], 0.25)
        self.assertIn("document.title = marker", client.scripts[0])
        self.assertIn('document.title = previous || ""', client.scripts[1])

    def test_apply_identity_skips_non_windows(self) -> None:
        client = FakeDevToolsClient()

        with (
            mock.patch("amazify.window_identity.os.name", "posix"),
            mock.patch("amazify.window_identity.tag_windows_with_exact_title") as tag_windows,
        ):
            tagged = apply_amazify_window_identity(client)

        self.assertEqual(tagged, 0)
        self.assertEqual(client.scripts, [])
        tag_windows.assert_not_called()

    def test_apply_identity_falls_back_to_amazon_music_windows(self) -> None:
        client = FakeDevToolsClient()

        with (
            mock.patch("amazify.window_identity.os.name", "nt"),
            mock.patch(
                "amazify.window_identity.tag_windows_with_exact_title",
                return_value=0,
            ),
            mock.patch(
                "amazify.window_identity.tag_amazon_music_windows",
                return_value=2,
            ) as tag_amazon_music,
        ):
            tagged = apply_amazify_window_identity(client, app_id="Amazify.Test")

        self.assertEqual(tagged, 2)
        tag_amazon_music.assert_called_once_with("Amazify.Test", timeout_seconds=2.5)
        self.assertIn("document.title = marker", client.scripts[0])
        self.assertIn('document.title = previous || ""', client.scripts[1])

    def test_amazon_music_window_matcher_excludes_amazify_and_rpc(self) -> None:
        self.assertTrue(
            _looks_like_amazon_music_window(
                "",
                "Chrome_WidgetWin_1",
                r"C:\Program Files\WindowsApps\AmazonMobileLLC.AmazonMusic_9.5.2.0_x86__kc6t79cpj4tp0\Amazon Music Helper.exe",
            )
        )
        self.assertTrue(
            _looks_like_amazon_music_window(
                "Amazon Music",
                "ApplicationFrameWindow",
                r"C:\Windows\System32\ApplicationFrameHost.exe",
            )
        )
        self.assertFalse(
            _looks_like_amazon_music_window(
                "Amazon Music (Amazify)",
                "Shell_TrayWnd",
                r"C:\Users\erikp\AppData\Local\Programs\Amazify\amazifyw.exe",
            )
        )
        self.assertFalse(
            _looks_like_amazon_music_window(
                "AmazonMusicRPC",
                "QtWindow",
                r"C:\Users\erikp\AppData\Local\Programs\Amazon Music RPC\AmazonMusicRPC.exe",
            )
        )


if __name__ == "__main__":
    unittest.main()
