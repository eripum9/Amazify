from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from amazify.cli import (
    connect_or_launch,
    connect_or_launch_result,
    daemon_spawn_command,
    main,
    recent_devtools_ports,
    remember_devtools_port,
    run,
    show_first_run_welcome,
)
from amazify.config import RuntimeConfig
from amazify.devtools import DevToolsError
from amazify.launcher import LaunchCandidate


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
            start_daemon.assert_called_once_with(args, config=config)

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
                mock.patch("amazify.cli.run_foreground", return_value=0) as run_foreground,
            ):
                exit_code = run(args)

            self.assertEqual(exit_code, 0)
            run_foreground.assert_called_once_with(args, config=config, daemon_mode=False)

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

        self.assertEqual(command, [str(sibling), "daemon", "run"])

    def test_recent_devtools_ports_prefers_state_then_recent_log_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp))
            config.devtools_state_file.write_text('{"last_port": 51172}', encoding="utf-8")
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

    def test_connect_or_launch_reuses_known_port_before_launching(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp), devtools_port=51394)
            config.devtools_state_file.write_text('{"last_port": 51172}', encoding="utf-8")
            target = object()

            class FakeDevToolsHttp:
                def __init__(self, port: int) -> None:
                    self.port = port

                def wait_for_amazon_music_target(self, timeout_seconds: float) -> object:
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

                def wait_for_amazon_music_target(self, timeout_seconds: float) -> object:
                    return target

            candidates = [LaunchCandidate("aumid", "AmazonMusic_app!App", "Amazon Music")]
            with (
                mock.patch("amazify.cli.DevToolsHttp", FakeDevToolsHttp),
                mock.patch("amazify.cli.discover_launch_candidates", return_value=candidates),
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
