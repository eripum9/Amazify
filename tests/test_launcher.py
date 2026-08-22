from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from amazify import launcher
from amazify.launcher import (
    LaunchCandidate,
    LaunchError,
    devtools_args,
    launch_candidate,
    running_amazon_music_devtools_ports,
    runtime_launch_candidates,
    validate_devtools_listener,
)


class LauncherTests(unittest.TestCase):
    def test_devtools_args_do_not_include_remote_origin_wildcard(self) -> None:
        self.assertEqual(
            devtools_args(61234),
            ["--remote-debugging-port=61234"],
        )

    def test_exe_launch_passes_devtools_args_separately(self) -> None:
        candidate = LaunchCandidate(
            "exe", "Amazon Music.exe", "Amazon Music executable"
        )

        with mock.patch("amazify.launcher.subprocess.Popen") as popen:
            launch_candidate(candidate, 61234)

        popen.assert_called_once()
        argv = popen.call_args.args[0]
        self.assertEqual(
            argv,
            [
                "Amazon Music.exe",
                "--remote-debugging-port=61234",
            ],
        )

    def test_aumid_launch_passes_devtools_args_as_single_activation_string(
        self,
    ) -> None:
        candidate = LaunchCandidate(
            "aumid", "AmazonMusic_app!App", "Amazon Music AUMID"
        )

        with mock.patch("amazify.launcher._activate_aumid") as activate:
            launch_candidate(candidate, 61234)

        activate.assert_called_once_with(
            "AmazonMusic_app!App",
            "--remote-debugging-port=61234",
        )

    def test_runtime_candidates_skip_powershell_discovery(self) -> None:
        candidates = runtime_launch_candidates()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].kind, "aumid")
        self.assertIn("AmazonMusic", candidates[0].value)

    def test_running_process_ports_are_deduplicated(self) -> None:
        process = mock.Mock()
        process.info = {
            "name": "Amazon Music.exe",
            "exe": r"C:\Program Files\WindowsApps\AmazonMobileLLC.AmazonMusic_1.0.0.0_x64__kc6t79cpj4tp0\Amazon Music.exe",
            "cmdline": ["Amazon Music.exe", "--remote-debugging-port=60364"],
        }
        psutil = mock.Mock()
        psutil.Error = OSError
        psutil.process_iter.return_value = [process, process]

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
        ):
            self.assertEqual(running_amazon_music_devtools_ports(), [60364])

    def test_running_process_ports_reject_user_writable_package_lookalike(
        self,
    ) -> None:
        process = mock.Mock()
        process.info = {
            "name": "Amazon Music.exe",
            "exe": r"C:\Users\Public\AmazonMobileLLC.AmazonMusic_1.0.0.0_x64__kc6t79cpj4tp0\Amazon Music.exe",
            "cmdline": ["Amazon Music.exe", "--remote-debugging-port=60364"],
        }
        psutil = mock.Mock()
        psutil.Error = OSError
        psutil.process_iter.return_value = [process]

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
        ):
            self.assertEqual(running_amazon_music_devtools_ports(), [])

    def test_launch_records_executable_process_id(self) -> None:
        candidate = LaunchCandidate(
            "exe", "Amazon Music.exe", "Amazon Music executable"
        )
        process = mock.Mock(pid=4242)

        with (
            mock.patch("amazify.launcher.subprocess.Popen", return_value=process),
            mock.patch("amazify.launcher._remember_expected_listener") as remember,
        ):
            process_id = launch_candidate(candidate, 61234)

        self.assertEqual(process_id, 4242)
        remember.assert_called_once_with(61234, 4242)


class ListenerOwnershipTests(unittest.TestCase):
    @staticmethod
    def _psutil(
        *,
        listener_host: str = "127.0.0.1",
        executable: str = r"C:\Program Files\WindowsApps\AmazonMobileLLC.AmazonMusic_1.0.0.0_x64__kc6t79cpj4tp0\Amazon Music.exe",
        process_id: int = 4242,
    ) -> mock.Mock:
        process = mock.Mock(pid=process_id)
        process.parents.return_value = []
        process.exe.return_value = executable
        process.create_time.return_value = 1_700_000_000.0
        psutil = mock.Mock()
        psutil.Error = OSError
        psutil.net_connections.return_value = [
            SimpleNamespace(
                status="LISTEN",
                laddr=(listener_host, 61234),
                pid=process_id,
            )
        ]
        psutil.Process.return_value = process
        return psutil

    def test_accepts_exact_packaged_amazon_music_listener(self) -> None:
        psutil = self._psutil()

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
        ):
            validate_devtools_listener(61234)

    def test_accepts_listener_descended_from_process_launched_by_amazify(self) -> None:
        psutil = self._psutil(executable=r"C:\Temp\custom-client.exe")

        with mock.patch.dict("sys.modules", {"psutil": psutil}), mock.patch.dict(
            "amazify.launcher._EXPECTED_LISTENERS", {}, clear=True
        ):
            launcher._remember_expected_listener(61234, 4242)
            validate_devtools_listener(61234)

    def test_rejects_reused_expected_process_id(self) -> None:
        psutil = self._psutil(executable=r"C:\Temp\custom-client.exe")
        psutil.Process.return_value.create_time.side_effect = [100.0, 200.0]

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch.dict(
                "amazify.launcher._EXPECTED_LISTENERS", {}, clear=True
            ),
            self.assertRaisesRegex(LaunchError, "non-Amazon process"),
        ):
            launcher._remember_expected_listener(61234, 4242)
            validate_devtools_listener(61234)

    def test_rejects_non_amazon_listener(self) -> None:
        psutil = self._psutil(executable=r"C:\Temp\not-amazon.exe")

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch.dict("amazify.launcher._EXPECTED_LISTENERS", {}, clear=True),
            self.assertRaisesRegex(LaunchError, "non-Amazon process"),
        ):
            validate_devtools_listener(61234)

    def test_rejects_listener_on_non_loopback_interface(self) -> None:
        psutil = self._psutil(listener_host="0.0.0.0")

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            self.assertRaisesRegex(LaunchError, "non-loopback interface"),
        ):
            validate_devtools_listener(61234)

    def test_rejects_packaged_lookalike_under_user_writable_root(self) -> None:
        psutil = self._psutil(
            executable=r"C:\Users\Public\AmazonMobileLLC.AmazonMusic_1.0.0.0_x64__kc6t79cpj4tp0\Amazon Music.exe"
        )

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch.dict("amazify.launcher._EXPECTED_LISTENERS", {}, clear=True),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
            self.assertRaisesRegex(LaunchError, "non-Amazon process"),
        ):
            validate_devtools_listener(61234)

    def test_rejects_malformed_package_directory_under_protected_root(self) -> None:
        psutil = self._psutil(
            executable=r"C:\Program Files\WindowsApps\AmazonMobileLLC.AmazonMusic_1\Amazon Music.exe"
        )

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch.dict("amazify.launcher._EXPECTED_LISTENERS", {}, clear=True),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
            self.assertRaisesRegex(LaunchError, "non-Amazon process"),
        ):
            validate_devtools_listener(61234)


if __name__ == "__main__":
    unittest.main()
