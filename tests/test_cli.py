from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from amazify.cli import (
    connect_or_launch,
    recent_devtools_ports,
    remember_devtools_port,
)
from amazify.config import RuntimeConfig
from amazify.devtools import DevToolsError


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
    def test_remember_devtools_port_writes_reusable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = make_config(Path(temp), devtools_port=61234)

            remember_devtools_port(config)

            self.assertIn('"last_port": 61234', config.devtools_state_file.read_text())

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


if __name__ == "__main__":
    unittest.main()
