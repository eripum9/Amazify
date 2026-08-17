from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amazify.shortcuts import create_amazify_shortcut, install_amazify_shortcuts


class ShortcutTests(unittest.TestCase):
    def test_create_shortcut_targets_amazify_run_with_embedded_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shortcut = root / "Desktop" / "Amazon Music (Amazify).lnk"
            target = root / "Amazify" / "amazify.exe"
            target.parent.mkdir()
            target.write_text("placeholder", encoding="utf-8")

            with mock.patch("amazify.shortcuts._run_powershell") as run_powershell:
                create_amazify_shortcut(shortcut, target)

            script = run_powershell.call_args.args[0]
            self.assertIn("$shortcut.Arguments = 'run'", script)
            self.assertIn("$shortcut.IconLocation = \"$targetPath,0\"", script)
            self.assertIn("Start Amazify and launch Amazon Music", script)

    def test_install_shortcuts_creates_start_menu_and_desktop_without_taskbar(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "Amazify" / "amazify.exe"
            target.parent.mkdir()
            target.write_text("placeholder", encoding="utf-8")

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(root / "AppData" / "Roaming"),
                        "USERPROFILE": str(root / "User"),
                    },
                    clear=False,
                ),
                mock.patch("amazify.shortcuts._run_powershell"),
            ):
                result = install_amazify_shortcuts(
                    target,
                    start_menu=True,
                    desktop=True,
                    taskbar=False,
                )

            created = {path.name for path in result.created}
            self.assertEqual(created, {"Amazon Music (Amazify).lnk"})
            self.assertEqual(len(result.created), 2)
            self.assertEqual(result.warnings, [])

    def test_desktop_shortcut_copies_installer_start_menu_shortcut_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "Amazify" / "amazify.exe"
            target.parent.mkdir()
            target.write_text("placeholder", encoding="utf-8")
            appdata = root / "AppData" / "Roaming"
            user = root / "User"
            start_menu_shortcut = (
                appdata
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Amazify"
                / "Amazon Music (Amazify).lnk"
            )
            start_menu_shortcut.parent.mkdir(parents=True)
            start_menu_shortcut.write_text("shortcut metadata", encoding="utf-8")
            legacy_start_menu_shortcut = (
                appdata
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Amazon Music (Amazify).lnk"
            )
            legacy_start_menu_shortcut.write_text("legacy shortcut metadata", encoding="utf-8")

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(appdata),
                        "USERPROFILE": str(user),
                    },
                    clear=False,
                ),
                mock.patch("amazify.shortcuts._run_powershell") as run_powershell,
            ):
                result = install_amazify_shortcuts(
                    target,
                    start_menu=False,
                    desktop=True,
                    taskbar=False,
                )

            desktop_shortcut = user / "Desktop" / "Amazon Music (Amazify).lnk"
            self.assertEqual(desktop_shortcut.read_text(encoding="utf-8"), "shortcut metadata")
            self.assertEqual(result.created, [desktop_shortcut])
            self.assertEqual(result.removed, [legacy_start_menu_shortcut])
            self.assertFalse(legacy_start_menu_shortcut.exists())
            run_powershell.assert_not_called()

    def test_taskbar_shortcut_is_refreshed_from_installer_start_menu_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "Amazify" / "amazify.exe"
            target.parent.mkdir()
            target.write_text("placeholder", encoding="utf-8")
            appdata = root / "AppData" / "Roaming"
            start_menu_shortcut = (
                appdata
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Amazify"
                / "Amazon Music (Amazify).lnk"
            )
            start_menu_shortcut.parent.mkdir(parents=True)
            start_menu_shortcut.write_text("shortcut metadata", encoding="utf-8")

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(appdata),
                        "USERPROFILE": str(root / "User"),
                    },
                    clear=False,
                ),
                mock.patch("amazify.shortcuts._run_powershell") as run_powershell,
            ):
                result = install_amazify_shortcuts(
                    target,
                    start_menu=False,
                    desktop=False,
                    taskbar=True,
                )

            taskbar_shortcut = (
                appdata
                / "Microsoft"
                / "Internet Explorer"
                / "Quick Launch"
                / "User Pinned"
                / "TaskBar"
                / "Amazon Music (Amazify).lnk"
            )
            self.assertEqual(taskbar_shortcut.read_text(encoding="utf-8"), "shortcut metadata")
            self.assertEqual(result.created, [taskbar_shortcut])
            self.assertEqual(result.warnings, [])
            run_powershell.assert_called_once()


if __name__ == "__main__":
    unittest.main()
