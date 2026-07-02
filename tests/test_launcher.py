from __future__ import annotations

import unittest
from unittest import mock

from amazify.launcher import LaunchCandidate, devtools_args, launch_candidate


class LauncherTests(unittest.TestCase):
    def test_devtools_args_include_remote_origin_allowlist(self) -> None:
        self.assertEqual(
            devtools_args(61234),
            [
                "--remote-debugging-port=61234",
                "--remote-allow-origins=*",
            ],
        )

    def test_exe_launch_passes_devtools_args_separately(self) -> None:
        candidate = LaunchCandidate("exe", "Amazon Music.exe", "Amazon Music executable")

        with mock.patch("amazify.launcher.subprocess.Popen") as popen:
            launch_candidate(candidate, 61234)

        popen.assert_called_once()
        argv = popen.call_args.args[0]
        self.assertEqual(
            argv,
            [
                "Amazon Music.exe",
                "--remote-debugging-port=61234",
                "--remote-allow-origins=*",
            ],
        )

    def test_aumid_launch_passes_devtools_args_as_single_activation_string(self) -> None:
        candidate = LaunchCandidate("aumid", "AmazonMusic_app!App", "Amazon Music AUMID")

        with mock.patch("amazify.launcher._activate_aumid") as activate:
            launch_candidate(candidate, 61234)

        activate.assert_called_once_with(
            "AmazonMusic_app!App",
            "--remote-debugging-port=61234 --remote-allow-origins=*",
        )


if __name__ == "__main__":
    unittest.main()
