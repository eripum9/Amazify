from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from amazify.cli import (
    ConnectedTarget,
    connect_or_launch,
    connect_or_launch_result,
    consume_daemon_launch_request,
    create_plugin_manager,
    daemon_spawn_command,
    inject_connection,
    main,
    recent_devtools_ports,
    remember_devtools_port,
    request_daemon_launch,
    run,
    show_first_run_welcome,
    status_daemon_command,
    update_command,
)
from amazify.config import RuntimeConfig
from amazify.devtools import DevToolsError
from amazify.launcher import LaunchCandidate
from amazify.plugin_manager import PluginError


def make_config(root: Path, devtools_port: int = 4444) -> RuntimeConfig:
    config = RuntimeConfig(
        state_dir=root,
        plugin_dir=root / "plugins",
        log_dir=root / "logs",
        devtools_port=devtools_port,
        bridge_port=5555,
        bridge_token="token",
    )
    config.ensure_dirs()
    return config


class CliDevToolsPortTests(unittest.TestCase):
    def test_injection_uses_one_runtime_evaluation_with_inline_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            client = mock.Mock()
            client.probe_amazon_music.return_value = {
                "title": "Amazon Music",
                "href": "https://music.amazon.com/",
            }
            client.evaluate.return_value = {"ok": True}
            native_bridge = mock.Mock()
            native_bridge.session_nonce = "native-session"
            native_bridge.response_callback_name = (
                "__amazifyNativeResult_" + "c" * 36
            )
            plugin_manager = mock.Mock()
            plugin_manager.runtime_snapshot.return_value = []
            plugin_manager.cached_catalog_payload.return_value = {"plugins": []}

            with (
                mock.patch("amazify.cli.DevToolsClient", return_value=client),
                mock.patch(
                    "amazify.cli.NativeBindingBridge", return_value=native_bridge
                ),
                mock.patch("amazify.cli.remember_devtools_port"),
                mock.patch("amazify.cli.build_cleanup_script") as cleanup_builder,
            ):
                result = inject_connection(
                    config,
                    plugin_manager,
                    ConnectedTarget(target=object(), launched_by_amazify=False),
                )

            self.assertIs(result, client)
            native_bridge.install.assert_called_once_with()
            cleanup_builder.assert_not_called()
            client.evaluate.assert_called_once()
            script = client.evaluate.call_args.args[0]
            cleanup_index = script.index("NATIVE_DISPATCH_EVENT(window")
            ownership_cleanup_index = script.index(
                "document.querySelectorAll('[data-amazify-plugin-id]"
            )
            self.assertLess(script.index("const NATIVE_JSON_STRINGIFY"), cleanup_index)
            self.assertLess(cleanup_index, ownership_cleanup_index)
            self.assertLess(ownership_cleanup_index, script.index("const BRIDGE_TOKEN"))

    def test_local_catalog_requires_source_build_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            catalog = Path(temp) / "catalog.json"
            catalog.write_text('{"schemaVersion": 2, "plugins": []}', encoding="utf-8")
            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "AMAZIFY_PLUGIN_CATALOG_URL": catalog.resolve().as_uri(),
                        "AMAZIFY_ALLOW_LOCAL_CATALOG": "1",
                    },
                    clear=False,
                ),
                mock.patch("amazify.cli.sys.frozen", False, create=True),
            ):
                manager = create_plugin_manager(config)
            self.assertEqual(manager.catalog_plugins(), [])

    def test_frozen_build_ignores_local_catalog_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            catalog = Path(temp) / "catalog.json"
            catalog.write_text('{"schemaVersion": 2, "plugins": []}', encoding="utf-8")
            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "AMAZIFY_PLUGIN_CATALOG_URL": catalog.resolve().as_uri(),
                        "AMAZIFY_ALLOW_LOCAL_CATALOG": "1",
                    },
                    clear=False,
                ),
                mock.patch("amazify.cli.sys.frozen", True, create=True),
                self.assertRaisesRegex(PluginError, "allow_local_catalog=True"),
            ):
                create_plugin_manager(config)

    def test_main_without_subcommand_prints_commands_without_running(self) -> None:
        output = io.StringIO()

        with mock.patch("amazify.cli.run") as run_command, redirect_stdout(output):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        run_command.assert_not_called()
        help_text = output.getvalue()
        self.assertIn("run", help_text)
        self.assertIn("list-candidates", help_text)

    def test_main_run_subcommand_starts_runner(self) -> None:
        with mock.patch("amazify.cli.run", return_value=0) as run_command:
            exit_code = main(["run"])

        self.assertEqual(exit_code, 0)
        run_command.assert_called_once()

    def test_main_dispatches_application_update_command(self) -> None:
        with mock.patch("amazify.cli.update_command", return_value=0) as command:
            exit_code = main(["update", "check"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(command.call_args.args[0].update_action, "check")

    def test_version_flag_reports_release_version(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "amazify 1.1.3")

    def test_update_install_requires_available_verified_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            updater = mock.Mock()
            updater.check_now.return_value = {
                "currentVersion": "1.0.0",
                "latestVersion": "1.1.0",
                "updateAvailable": True,
                "releaseUrl": "https://github.com/eripum9/Amazify/releases/tag/v1.1.0",
            }
            args = mock.Mock(update_action="install", yes=True, json=False)
            output = io.StringIO()
            with (
                mock.patch("amazify.cli.RuntimeConfig.create", return_value=config),
                mock.patch(
                    "amazify.cli.create_application_updater", return_value=updater
                ),
                redirect_stdout(output),
            ):
                exit_code = update_command(args)

        self.assertEqual(exit_code, 0)
        updater.check_now.assert_called_once_with()
        updater.install_now.assert_called_once_with()
        self.assertIn("Verified Amazify 1.1.0 installer launched", output.getvalue())

    def test_run_starts_daemon_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            args = mock.Mock(
                devtools_port=None,
                bridge_port=None,
                manual_launcher=None,
                foreground=False,
                once=False,
            )

            with (
                mock.patch("amazify.cli.RuntimeConfig.create", return_value=config),
                mock.patch("amazify.cli.show_first_run_welcome") as welcome,
                mock.patch("amazify.cli.start_daemon", return_value=0) as start_daemon,
            ):
                exit_code = run(args)

            self.assertEqual(exit_code, 0)
            welcome.assert_called_once_with(config)
            start_daemon.assert_called_once_with(
                args, config=config, request_launch=True
            )

    def test_run_once_uses_foreground_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            args = mock.Mock(
                devtools_port=None,
                bridge_port=None,
                manual_launcher=None,
                foreground=False,
                once=True,
            )

            with (
                mock.patch("amazify.cli.RuntimeConfig.create", return_value=config),
                mock.patch("amazify.cli.show_first_run_welcome"),
                mock.patch(
                    "amazify.cli.run_foreground", return_value=0
                ) as run_foreground,
            ):
                exit_code = run(args)

            self.assertEqual(exit_code, 0)
            run_foreground.assert_called_once_with(
                args, config=config, daemon_mode=False
            )

    def test_remember_devtools_port_writes_reusable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp), devtools_port=61234)

            remember_devtools_port(config)

            self.assertIn('"last_port": 61234', config.devtools_state_file.read_text())

    def test_first_run_welcome_prints_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            first_output = io.StringIO()
            second_output = io.StringIO()

            with redirect_stdout(first_output):
                first_shown = show_first_run_welcome(config)
            with redirect_stdout(second_output):
                second_shown = show_first_run_welcome(config)

            self.assertTrue(first_shown)
            self.assertFalse(second_shown)
            self.assertIn("Welcome to Amazify", first_output.getvalue())
            self.assertIn("Amazon Music (Amazify)", first_output.getvalue())
            self.assertEqual(second_output.getvalue(), "")
            self.assertTrue(config.welcome_state_file.exists())

    def test_daemon_spawn_command_uses_module_entry_for_source_runs(self) -> None:
        args = mock.Mock(
            devtools_port=61234,
            bridge_port=None,
            manual_launcher="AmazonMusic_app!App",
            connect_only=True,
            verbose=True,
        )

        with (
            mock.patch("amazify.cli.sys.frozen", False, create=True),
            mock.patch("amazify.cli.sys.executable", "python.exe"),
        ):
            command = daemon_spawn_command(args)

        self.assertEqual(
            command,
            [
                "python.exe",
                "-m",
                "amazify",
                "--verbose",
                "daemon",
                "run",
                "--devtools-port",
                "61234",
                "--manual-launcher",
                "AmazonMusic_app!App",
                "--connect-only",
            ],
        )

    def test_daemon_spawn_command_prefers_windowed_sibling_for_frozen_cli(self) -> None:
        args = mock.Mock(
            devtools_port=None,
            bridge_port=None,
            manual_launcher=None,
            connect_only=False,
            verbose=False,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sibling = root / "amazifyw" / "amazifyw.exe"
            sibling.parent.mkdir()
            sibling.write_text("placeholder", encoding="utf-8")

            with (
                mock.patch("amazify.cli.sys.frozen", True, create=True),
                mock.patch("amazify.cli.sys.executable", str(root / "amazify.exe")),
            ):
                command = daemon_spawn_command(args)

        self.assertEqual(command, [str(sibling.resolve()), "daemon", "run"])

    def test_daemon_spawn_command_can_launch_on_worker_start(self) -> None:
        args = mock.Mock(
            devtools_port=None,
            bridge_port=None,
            manual_launcher=None,
            connect_only=False,
            verbose=False,
        )
        with (
            mock.patch("amazify.cli.sys.frozen", False, create=True),
            mock.patch("amazify.cli.sys.executable", "python.exe"),
        ):
            command = daemon_spawn_command(args, launch_on_start=True)

        self.assertEqual(
            command,
            ["python.exe", "-m", "amazify", "daemon", "run", "--launch-on-start"],
        )

    def test_launch_request_file_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            request_daemon_launch(config)

            self.assertTrue(config.daemon_launch_file.exists())
            self.assertTrue(consume_daemon_launch_request(config))
            self.assertFalse(consume_daemon_launch_request(config))

    def test_recent_devtools_ports_prefers_state_then_recent_log_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            config.devtools_state_file.write_text(
                '{"last_port": 51172}', encoding="utf-8"
            )
            (config.log_dir / "amazify.log").write_text(
                "\n".join(
                    [
                        "Launching Amazon Music AUMID with DevTools port 50076",
                        "Launching Amazon Music AUMID with DevTools port 51394",
                        "Launching Amazon Music AUMID with DevTools port 51394",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(recent_devtools_ports(config), [51172, 51394, 50076])

    def test_daemon_status_ignores_invalid_pid_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            config.daemon_state_file.write_text(
                '{"pid":{"invalid":true},"status":"idle"}', encoding="utf-8"
            )
            output = io.StringIO()

            with (
                mock.patch("amazify.cli.RuntimeConfig.create", return_value=config),
                mock.patch("amazify.cli.is_pid_running") as is_pid_running,
                redirect_stdout(output),
            ):
                exit_code = status_daemon_command(mock.Mock())

            self.assertEqual(exit_code, 1)
            self.assertIn("Amazify daemon: stopped", output.getvalue())
            is_pid_running.assert_not_called()

    def test_connect_or_launch_reuses_known_port_before_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp), devtools_port=51394)
            config.devtools_state_file.write_text(
                '{"last_port": 51172}', encoding="utf-8"
            )
            target = object()

            class FakeDevToolsHttp:
                def __init__(self, port: int) -> None:
                    self.port = port

                def wait_for_amazon_music_target(
                    self, timeout_seconds: float
                ) -> object:
                    if self.port == 51172:
                        return target
                    raise DevToolsError("missing")

            with (
                mock.patch("amazify.cli.DevToolsHttp", FakeDevToolsHttp),
                mock.patch("amazify.cli.launch_candidate") as launch_candidate,
            ):
                result = connect_or_launch(
                    config,
                    connect_only=False,
                    prefer_known_ports=True,
                )

            self.assertIs(result, target)
            self.assertEqual(config.devtools_port, 51172)
            launch_candidate.assert_not_called()

    def test_connect_or_launch_result_marks_fresh_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp), devtools_port=51394)
            target = object()

            class FakeDevToolsHttp:
                def __init__(self, port: int) -> None:
                    self.port = port

                def wait_for_amazon_music_target(
                    self, timeout_seconds: float
                ) -> object:
                    return target

            candidates = [
                LaunchCandidate("aumid", "AmazonMusic_app!App", "Amazon Music")
            ]
            with (
                mock.patch("amazify.cli.DevToolsHttp", FakeDevToolsHttp),
                mock.patch(
                    "amazify.cli.runtime_launch_candidates", return_value=candidates
                ),
                mock.patch("amazify.cli.amazon_music_is_running", return_value=False),
                mock.patch("amazify.cli.launch_candidate") as launch_candidate,
            ):
                result = connect_or_launch_result(
                    config,
                    connect_only=False,
                    prefer_known_ports=False,
                )

            self.assertIs(result.target, target)
            self.assertTrue(result.launched_by_amazify)
            launch_candidate.assert_called_once_with(candidates[0], 51394)


if __name__ == "__main__":
    unittest.main()
