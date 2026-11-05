from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from amazify import launcher
from amazify.launcher import (
    DevToolsListenerNotReady,
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

    def test_reports_listener_not_ready_when_no_process_listens(self) -> None:
        psutil = mock.Mock()
        psutil.Error = OSError
        psutil.net_connections.return_value = []

        with (
            mock.patch.dict("sys.modules", {"psutil": psutil}),
            mock.patch("amazify.launcher.socket.create_connection", side_effect=OSError),
            self.assertRaisesRegex(DevToolsListenerNotReady, "listener owner"),
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


class ProbeOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.psutil = ListenerOwnershipTests._psutil()
        self.bound = SimpleNamespace(
            status="NONE", laddr=("127.0.0.1", 61234), raddr=(), pid=4242
        )
        self.server = SimpleNamespace(
            status="ESTABLISHED",
            laddr=("127.0.0.1", 61234),
            raddr=("127.0.0.1", 55670),
            pid=4242,
        )
        self.psutil.net_connections.return_value = [self.bound, self.server]
        self.probe = mock.MagicMock()
        self.probe.__enter__.return_value = self.probe
        self.probe.getsockname.return_value = ("127.0.0.1", 55670)
        self.probe.getpeername.return_value = ("127.0.0.1", 61234)
        self.connect = mock.Mock(return_value=self.probe)
        self.now = 0.0
        self.sleep = mock.Mock(side_effect=self._advance_time)
        for patcher in (
            mock.patch.dict("sys.modules", {"psutil": self.psutil}),
            mock.patch.dict("amazify.launcher._EXPECTED_LISTENERS", {}, clear=True),
            mock.patch(
                "amazify.launcher._protected_windows_apps_roots",
                return_value=frozenset({r"C:\Program Files\WindowsApps"}),
            ),
            mock.patch("amazify.launcher.socket.create_connection", self.connect),
            mock.patch("amazify.launcher.time.monotonic", side_effect=lambda: self.now),
            mock.patch("amazify.launcher.time.sleep", self.sleep),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _advance_time(self, seconds: float) -> None:
        self.now += seconds

    def tearDown(self) -> None:
        if self.probe.__enter__.called:
            self.probe.__exit__.assert_called_once()
        self.probe.send.assert_not_called()
        self.probe.sendall.assert_not_called()
        self.probe.recv.assert_not_called()

    def test_accepts_only_exact_held_probe_server_owner(self) -> None:
        validate_devtools_listener(61234)
        self.connect.assert_called_once_with(
            ("127.0.0.1", 61234), timeout=launcher.DEVTOOLS_PROBE_TIMEOUT_SECONDS
        )
        self.assertEqual(self.psutil.net_connections.call_count, 2)
        self.psutil.Process.assert_called_once_with(4242)

    def test_waits_for_delayed_server_row_on_same_held_probe(self) -> None:
        self.psutil.net_connections.side_effect = [
            [self.bound], [self.bound], [self.bound, self.server]
        ]
        validate_devtools_listener(61234)
        self.connect.assert_called_once()
        self.probe.getsockname.assert_called_once()
        self.probe.getpeername.assert_called_once()
        self.sleep.assert_called_once_with(0.05)
        self.assertEqual(self.psutil.net_connections.call_count, 3)

    def test_unknown_listener_requires_probe_by_default(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        with self.assertRaises(DevToolsListenerNotReady):
            launcher._devtools_listener_pids([unknown], 61234)

    def test_unknown_listener_accepts_exact_trusted_probe(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        self.psutil.net_connections.return_value.insert(0, unknown)
        validate_devtools_listener(61234)
        self.connect.assert_called_once()
        self.psutil.Process.assert_called_once_with(4242)

    def test_unknown_listener_without_exact_probe_fails_closed(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=None
        )
        self.server.raddr = ("127.0.0.1", 55671)
        self.psutil.net_connections.return_value.insert(0, unknown)
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)
        self.psutil.Process.assert_not_called()
        self.assertEqual(self.now, launcher.DEVTOOLS_PROBE_DISCOVERY_SECONDS)

    def test_known_and_unknown_listeners_accept_exact_trusted_probe(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        self.bound.status = "LISTEN"
        self.psutil.net_connections.return_value.insert(0, unknown)
        validate_devtools_listener(61234)
        self.connect.assert_called_once()
        self.assertEqual(self.psutil.Process.call_args_list, [mock.call(4242)] * 3)

    def test_known_trusted_listener_cannot_bypass_unknown_listener_probe(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        self.bound.status = "LISTEN"
        self.psutil.net_connections.return_value = [unknown, self.bound]
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)
        self.connect.assert_called_once()

    def test_unknown_listener_cannot_hide_known_malicious_listener(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        malicious = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=4243
        )
        good_process = self.psutil.Process.return_value
        bad_process = mock.Mock(pid=4243)
        bad_process.parents.return_value = []
        bad_process.exe.return_value = r"C:\Temp\not-amazon.exe"
        self.psutil.Process.side_effect = lambda pid: (
            good_process if pid == 4242 else bad_process
        )
        # Exercise both row orders and both the initial and refreshed snapshot.
        for rows in ([unknown, malicious], [malicious, unknown]):
            for during_probe in (False, True):
                with self.subTest(rows=rows, during_probe=during_probe):
                    self.connect.reset_mock()
                    self.probe.reset_mock()
                    self.psutil.net_connections.side_effect = [
                        [self.bound] if during_probe else rows,
                        [*rows, self.server],
                    ]
                    with self.assertRaisesRegex(LaunchError, "non-Amazon process"):
                        validate_devtools_listener(61234)
                    if during_probe:
                        self.probe.__exit__.assert_called_once()
                    else:
                        self.connect.assert_not_called()

    def test_unknown_listener_cannot_hide_non_loopback_row(self) -> None:
        unknown = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=0
        )
        self.bound.laddr = ("0.0.0.0", 61234)
        self.psutil.net_connections.return_value.insert(0, unknown)
        with self.assertRaisesRegex(LaunchError, "non-loopback"):
            validate_devtools_listener(61234)
        self.connect.assert_not_called()

    def test_missing_server_row_polling_has_deadline(self) -> None:
        self.psutil.net_connections.return_value = [self.bound]
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)
        self.connect.assert_called_once()
        self.assertEqual(self.now, launcher.DEVTOOLS_PROBE_DISCOVERY_SECONDS)
        self.assertLessEqual(self.psutil.net_connections.call_count, 23)

    def test_untrusted_listener_during_polling_fails_immediately(self) -> None:
        unsafe = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=4242
        )
        self.psutil.Process.return_value.exe.return_value = r"C:\Temp\not-amazon.exe"
        self.psutil.net_connections.side_effect = [
            [self.bound], [self.bound], [unsafe]
        ]
        with self.assertRaisesRegex(LaunchError, "non-Amazon process"):
            validate_devtools_listener(61234)
        self.sleep.assert_called_once_with(0.05)
        self.assertEqual(self.psutil.net_connections.call_count, 3)

    def test_normal_listener_does_not_probe(self) -> None:
        self.bound.status = "LISTEN"
        validate_devtools_listener(61234)
        self.connect.assert_not_called()
        self.assertEqual(self.psutil.net_connections.call_count, 1)

    def test_none_row_alone_is_not_trusted(self) -> None:
        self.psutil.net_connections.return_value = [self.bound]
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)
        self.psutil.Process.assert_not_called()

    def test_unrelated_connection_or_wrong_state_is_not_trusted(self) -> None:
        for field, value in (
            ("raddr", ("127.0.0.1", 55671)),
            ("raddr", ("::1", 55670)),
            ("laddr", ("127.0.0.1", 61235)),
            ("status", "NONE"),
            ("status", "CLOSE_WAIT"),
        ):
            with self.subTest(field=field, value=value):
                original = getattr(self.server, field)
                setattr(self.server, field, value)
                self.probe.reset_mock()
                with self.assertRaises(DevToolsListenerNotReady):
                    validate_devtools_listener(61234)
                self.probe.__exit__.assert_called_once()
                setattr(self.server, field, original)
        self.psutil.Process.assert_not_called()

    def test_rejects_client_side_row_instead_of_server(self) -> None:
        self.server.laddr, self.server.raddr = self.server.raddr, self.server.laddr
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)

    def test_rejects_unidentified_probe_owner(self) -> None:
        self.server.pid = None
        with self.assertRaisesRegex(LaunchError, "could not identify"):
            validate_devtools_listener(61234)

    def test_rejects_conflicting_exact_probe_owners(self) -> None:
        conflict = SimpleNamespace(**{**vars(self.server), "pid": 4243})
        self.psutil.net_connections.return_value.append(conflict)
        with self.assertRaisesRegex(LaunchError, "conflicting owners"):
            validate_devtools_listener(61234)

    def test_rejects_untrusted_probe_owner(self) -> None:
        self.psutil.Process.return_value.exe.return_value = r"C:\Temp\not-amazon.exe"
        with self.assertRaisesRegex(LaunchError, "non-Amazon process"):
            validate_devtools_listener(61234)

    def test_rejects_reused_expected_probe_pid(self) -> None:
        self.psutil.Process.return_value.exe.return_value = r"C:\Temp\custom.exe"
        self.psutil.Process.return_value.create_time.side_effect = [100.0, 200.0]
        launcher._remember_expected_listener(61234, 4242)
        with self.assertRaisesRegex(LaunchError, "non-Amazon process"):
            validate_devtools_listener(61234)

    def test_checks_new_listener_owner_in_refreshed_snapshot(self) -> None:
        untrusted = SimpleNamespace(
            status="LISTEN", laddr=("127.0.0.1", 61234), pid=4243
        )
        self.psutil.net_connections.side_effect = [
            [self.bound], [self.bound, self.server, untrusted]
        ]
        bad_process = mock.Mock(pid=4243)
        bad_process.parents.return_value = []
        bad_process.exe.return_value = r"C:\Temp\not-amazon.exe"
        good_process = self.psutil.Process.return_value
        self.psutil.Process.side_effect = lambda pid: (
            good_process if pid == 4242 else bad_process
        )
        with self.assertRaisesRegex(LaunchError, "non-Amazon process"):
            validate_devtools_listener(61234)

    def test_rejects_non_loopback_bound_row_without_probing(self) -> None:
        self.bound.laddr = ("0.0.0.0", 61234)
        with self.assertRaisesRegex(LaunchError, "non-loopback"):
            validate_devtools_listener(61234)
        self.connect.assert_not_called()

    def test_rejects_non_loopback_row_appearing_during_probe(self) -> None:
        unsafe = SimpleNamespace(
            status="NONE", laddr=("0.0.0.0", 61234), raddr=(), pid=4242
        )
        self.psutil.net_connections.side_effect = [
            [self.bound], [self.server, unsafe]
        ]
        with self.assertRaisesRegex(LaunchError, "non-loopback"):
            validate_devtools_listener(61234)

    def test_probe_failures_are_bounded_and_retryable(self) -> None:
        self.connect.side_effect = TimeoutError
        with self.assertRaises(DevToolsListenerNotReady):
            validate_devtools_listener(61234)
        self.assertEqual(self.connect.call_count, 2)
        for call in self.connect.call_args_list:
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 0.5)
        self.probe.__enter__.assert_not_called()

    def test_supports_exact_ipv6_probe_tuple(self) -> None:
        self.bound.laddr = self.server.laddr = ("::1", 61234)
        self.server.raddr = ("::1", 55670)
        self.probe.getsockname.return_value = ("::1", 55670, 0, 0)
        self.probe.getpeername.return_value = ("::1", 61234, 0, 0)
        self.connect.side_effect = [ConnectionRefusedError(), self.probe]
        validate_devtools_listener(61234)
        self.assertEqual(self.connect.call_count, 2)

    def test_snapshot_error_fails_closed_and_closes_probe(self) -> None:
        self.psutil.net_connections.side_effect = [[self.bound], OSError()]
        with self.assertRaisesRegex(LaunchError, "could not verify"):
            validate_devtools_listener(61234)


if __name__ == "__main__":
    unittest.main()
