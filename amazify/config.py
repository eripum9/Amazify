from __future__ import annotations

import os
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "Amazify"
DEVTOOLS_HOST = "127.0.0.1"
DEFAULT_KNOWN_AUMID = (
    "AmazonMobileLLC.AmazonMusic_kc6t79cpj4tp0!AmazonMobileLLC.AmazonMusic"
)
AMAZIFY_WINDOW_APP_USER_MODEL_ID = "Amazify.AmazonMusic"


def appdata_root() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DEVTOOLS_HOST, 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class RuntimeConfig:
    state_dir: Path
    plugin_dir: Path
    log_dir: Path
    devtools_port: int
    bridge_port: int
    bridge_token: str
    manual_launcher: str | None = None

    @classmethod
    def create(
        cls,
        *,
        devtools_port: int | None = None,
        bridge_port: int | None = None,
        manual_launcher: str | None = None,
    ) -> "RuntimeConfig":
        root = appdata_root()
        state_dir = root
        plugin_dir = root / "plugins"
        log_dir = root / "logs"
        config = cls(
            state_dir=state_dir,
            plugin_dir=plugin_dir,
            log_dir=log_dir,
            devtools_port=devtools_port or find_free_local_port(),
            bridge_port=bridge_port or find_free_local_port(),
            bridge_token=secrets.token_urlsafe(32),
            manual_launcher=manual_launcher,
        )
        config.ensure_dirs()
        return config

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def plugin_state_file(self) -> Path:
        return self.state_dir / "plugins_state.json"

    @property
    def devtools_state_file(self) -> Path:
        return self.state_dir / "devtools_state.json"

    @property
    def daemon_state_file(self) -> Path:
        return self.state_dir / "daemon_state.json"

    @property
    def daemon_stop_file(self) -> Path:
        return self.state_dir / "daemon_stop"

    @property
    def welcome_state_file(self) -> Path:
        return self.state_dir / "welcome_state.json"

    @property
    def bridge_url(self) -> str:
        return f"http://{DEVTOOLS_HOST}:{self.bridge_port}"
