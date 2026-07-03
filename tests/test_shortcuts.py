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
            self.assertIn("Amazon Music through Amazify", script)

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


if __name__ == "__main__":
    unittest.main()
