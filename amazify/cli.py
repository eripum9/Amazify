from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from . import __version__
from .app_updater import ApplicationUpdater, UpdateError
from .bridge import LocalBridge
from .config import RuntimeConfig, find_free_local_port
from .devtools import (
    DevToolsClient,
    DevToolsConnectionClosed,
    DevToolsError,
    DevToolsHttp,
    Target,
)
from .launcher import (
    LaunchError,
    amazon_music_is_running,
    discover_launch_candidates,
    focus_amazon_music,
    launch_candidate,
    running_amazon_music_devtools_ports,
    runtime_launch_candidates,
)
from .logging_setup import setup_logging
from .native_bridge import NativeBindingBridge
from .plugin_manager import PluginManager
from .runtime import build_cleanup_script, build_runtime_script
from .window_identity import apply_amazify_window_identity

LOG = logging.getLogger(__name__)


WELCOME_STATE_VERSION = 1
DAEMON_STATE_VERSION = 1
DAEMON_START_TIMEOUT_SECONDS = 8
DAEMON_STOP_TIMEOUT_SECONDS = 10
DAEMON_HEARTBEAT_SECONDS = 2
AUMID_TARGET_TIMEOUT_SECONDS = 20
EXE_TARGET_TIMEOUT_SECONDS = 15
KNOWN_PORT_PROBE_TIMEOUT_SECONDS = 0.6
KNOWN_PORT_LIMIT = 8
DAEMON_POLL_SECONDS = 0.1
DAEMON_AUTO_ATTACH_SECONDS = 1.0
DAEMON_MUTEX_NAME = "Local\\AmazifyLaunchSupervisor"
DEVTOOLS_PORT_PATTERN = re.compile(r"(?:DevTools port:|with DevTools port)\s*(\d+)")


@dataclass(slots=True)
class ConnectedTarget:
    target: Target
    launched_by_amazify: bool = False


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "list-candidates":
        return list_candidates(args)
    if args.command == "daemon":
        return daemon_command(args)
    if args.command == "start":
        return start_daemon_command(args)
    if args.command == "stop":
        return stop_daemon_command(args)
    if args.command == "status":
        return status_daemon_command(args)
    if args.command == "shortcuts":
        return shortcuts_command(args)
    if args.command == "update":
        return update_command(args)
    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazify",
        description="Amazify Amazon Music runtime customization companion.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Launch/connect and inject Amazify.")
    add_launch_arguments(run_parser)
    run_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run Amazify in the current terminal instead of starting the daemon.",
    )
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Inject once and exit. The bridge will not remain available.",
    )
    run_parser.set_defaults(command="run")

    candidate_parser = subparsers.add_parser(
        "list-candidates",
        help="Print discovered Amazon Music launch candidates.",
    )
    candidate_parser.add_argument("--manual-launcher", default=None)

    start_parser = subparsers.add_parser("start", help="Start the Amazify daemon.")
    add_launch_arguments(start_parser)
    start_parser.set_defaults(daemon_action="start")

    stop_parser = subparsers.add_parser("stop", help="Stop the Amazify daemon.")
    stop_parser.set_defaults(daemon_action="stop")

    status_parser = subparsers.add_parser("status", help="Show Amazify daemon status.")
    status_parser.set_defaults(daemon_action="status")

    daemon_parser = subparsers.add_parser("daemon", help="Manage the Amazify daemon.")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_action")
    daemon_start_parser = daemon_subparsers.add_parser(
        "start", help="Start the daemon."
    )
    add_launch_arguments(daemon_start_parser)
    daemon_subparsers.add_parser("stop", help="Stop the daemon.")
    daemon_subparsers.add_parser("status", help="Show daemon status.")
    daemon_run_parser = daemon_subparsers.add_parser(
        "run",
        help="Run the daemon worker in the current process.",
    )
    add_launch_arguments(daemon_run_parser)
    daemon_run_parser.add_argument(
        "--launch-on-start",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    shortcuts_parser = subparsers.add_parser(
        "shortcuts",
        help="Install or remove Amazify launch shortcuts.",
    )
    shortcuts_subparsers = shortcuts_parser.add_subparsers(dest="shortcuts_action")
    shortcuts_install = shortcuts_subparsers.add_parser(
        "install", help="Install shortcuts."
    )
    shortcuts_install.add_argument("--start-menu", action="store_true")
    shortcuts_install.add_argument("--desktop", action="store_true")
    shortcuts_install.add_argument("--taskbar", action="store_true")
    shortcuts_install.add_argument("--target-exe", default=None)
    shortcuts_subparsers.add_parser("remove", help="Remove shortcuts.")

    update_parser = subparsers.add_parser(
        "update",
        help="Check for or install an Amazify application update.",
    )
    update_subparsers = update_parser.add_subparsers(dest="update_action")
    update_check = update_subparsers.add_parser(
        "check",
        help="Check the latest final GitHub release.",
    )
    update_check.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable update status.",
    )
    update_install = update_subparsers.add_parser(
        "install",
        help="Download, verify, and launch the latest installer.",
    )
    update_install.add_argument(
        "--yes",
        action="store_true",
        help="Install without the interactive command-line confirmation.",
    )

    return parser


def add_launch_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--devtools-port",
        type=int,
        default=None,
        help="Use a specific DevTools port instead of a random free port.",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        default=None,
        help="Use a specific localhost bridge port instead of a random free port.",
    )
    parser.add_argument(
        "--manual-launcher",
        default=None,
        help="Manual Amazon Music executable path or AUMID.",
    )
    parser.add_argument(
        "--connect-only",
        action="store_true",
        help="Do not launch Amazon Music; connect to an existing DevTools target.",
    )


def create_plugin_manager(config: RuntimeConfig) -> PluginManager:
    allow_local_catalog = bool(
        not getattr(sys, "frozen", False)
        and os.environ.get("AMAZIFY_ALLOW_LOCAL_CATALOG") == "1"
    )
    return PluginManager(
        config.plugin_dir,
        config.plugin_state_file,
        allow_local_catalog=allow_local_catalog,
    )


def create_application_updater(config: RuntimeConfig) -> ApplicationUpdater:
    return ApplicationUpdater(config.update_dir, current_version=__version__)


def run(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    show_first_run_welcome(config)
    if getattr(args, "foreground", False) or getattr(args, "once", False):
        return run_foreground(args, config=config, daemon_mode=False)
    return start_daemon(args, config=config, request_launch=True)


def run_foreground(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig | None = None,
    daemon_mode: bool = False,
) -> int:
    if config is None:
        config = RuntimeConfig.create(
            devtools_port=getattr(args, "devtools_port", None),
            bridge_port=getattr(args, "bridge_port", None),
            manual_launcher=getattr(args, "manual_launcher", None),
        )
    log_file = setup_logging(config.log_dir, verbose=args.verbose)
    LOG.info("Amazify %sstarting. Logs: %s", "daemon " if daemon_mode else "", log_file)

    plugin_manager = create_plugin_manager(config)
    app_updater = create_application_updater(config)

    bridge = LocalBridge(
        port=config.bridge_port,
        token=config.bridge_token,
        plugin_manager=plugin_manager,
    )
    bridge.start()

    client: DevToolsClient | None = None
    stop_requested = False

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        LOG.info("Stop requested")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        if daemon_mode:
            mark_daemon_state(
                config,
                status="starting",
                message="Amazify daemon is starting.",
                log_file=log_file,
            )
            remove_daemon_stop_file(config)
        explicit_devtools_port = getattr(args, "devtools_port", None) is not None
        connection = connect_or_launch_result(
            config,
            connect_only=getattr(args, "connect_only", False),
            prefer_known_ports=not explicit_devtools_port,
        )
        client = inject_connection(
            config,
            plugin_manager,
            connection,
            app_updater=app_updater,
        )
        mark_daemon_state(
            config,
            status="connected" if daemon_mode else "foreground",
            message="Amazify is injected into Amazon Music.",
            log_file=log_file,
        )
        emit("Amazify injected into Amazon Music.")
        emit(f"DevTools port: {config.devtools_port}")
        emit(f"Bridge: {config.bridge_url}")
        emit(f"Plugins: {config.plugin_dir}")
        emit(f"Logs: {log_file}")

        if getattr(args, "once", False):
            LOG.warning(
                "--once exits immediately; bridge-backed UI commands will stop working."
            )
            return 0

        last_heartbeat = 0.0
        while not stop_requested:
            if daemon_mode and config.daemon_stop_file.exists():
                LOG.info("Stop requested by daemon stop file")
                stop_requested = True
                break
            try:
                client.pump(timeout=0.5)
            except DevToolsConnectionClosed as exc:
                LOG.info("DevTools connection closed: %s", exc)
                return 0
            except DevToolsError as exc:
                LOG.info("DevTools event pump stopped: %s", exc)
                if not daemon_mode:
                    time.sleep(0.5)
                    continue
                raise
            if (
                daemon_mode
                and time.monotonic() - last_heartbeat >= DAEMON_HEARTBEAT_SECONDS
            ):
                last_heartbeat = time.monotonic()
                mark_daemon_state(
                    config,
                    status="connected",
                    message="Amazify is injected into Amazon Music.",
                    log_file=log_file,
                )
        return 0
    except (DevToolsError, LaunchError, OSError) as exc:
        LOG.exception("Amazify failed")
        if daemon_mode:
            mark_daemon_state(
                config,
                status="error",
                message=str(exc),
                log_file=log_file,
            )
        emit(f"Amazify failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            try:
                client.evaluate(build_cleanup_script())
            except Exception:
                LOG.debug("Cleanup injection failed during shutdown", exc_info=True)
            client.close()
        bridge.stop()
        if daemon_mode:
            mark_daemon_state(
                config,
                status="stopped",
                message="Amazify daemon stopped.",
                log_file=log_file,
                pid=0,
            )
            remove_daemon_stop_file(config)


def inject_connection(
    config: RuntimeConfig,
    plugin_manager: PluginManager,
    connection: ConnectedTarget,
    *,
    app_updater: ApplicationUpdater | None = None,
) -> DevToolsClient:
    if app_updater is None:
        app_updater = create_application_updater(config)
    client = DevToolsClient(connection.target)
    try:
        client.connect()
        native_bridge = NativeBindingBridge(
            client,
            plugin_manager,
            app_updater,
            lyrics_state_dir=config.state_dir,
        )
        native_bridge.install()
        probe = client.probe_amazon_music()
        remember_devtools_port(config)
        LOG.info(
            "Connected to Amazon Music target: title=%r url=%r",
            probe.get("title"),
            probe.get("href"),
        )
        if connection.launched_by_amazify:
            try:
                tagged_windows = apply_amazify_window_identity(client)
                if tagged_windows:
                    LOG.info(
                        "Applied Amazify taskbar identity to %s Amazon Music window(s)",
                        tagged_windows,
                    )
                else:
                    LOG.info(
                        "No native Amazon Music window was tagged for Amazify identity"
                    )
            except Exception as exc:
                LOG.debug(
                    "Unable to apply Amazify taskbar identity: %s", exc, exc_info=True
                )
        result = client.evaluate(
            build_runtime_script(
                bridge_url=config.bridge_url,
                bridge_token=config.bridge_token,
                plugins=plugin_manager.runtime_snapshot(),
                catalog_plugins=plugin_manager.cached_catalog_payload()["plugins"],
                native_session_nonce=native_bridge.session_nonce,
                native_response_callback=native_bridge.response_callback_name,
                app_update=app_updater.snapshot(),
            )
        )
        LOG.info("Injected Amazify runtime: %s", result)
        return client
    except Exception:
        client.close()
        raise


def daemon_command(args: argparse.Namespace) -> int:
    action = getattr(args, "daemon_action", None)
    if action == "start":
        return start_daemon_command(args)
    if action == "stop":
        return stop_daemon_command(args)
    if action == "status":
        return status_daemon_command(args)
    if action == "run":
        return run_daemon(args)
    emit("Choose a daemon command: start, stop, or status.", file=sys.stderr)
    return 2


def start_daemon_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    return start_daemon(args, config=config)


def stop_daemon_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create()
    state = read_daemon_state(config)
    pid = _coerce_int(state.get("pid")) or 0
    if not pid or not is_pid_running(pid):
        emit("Amazify daemon is not running.")
        mark_daemon_state(
            config,
            status="stopped",
            message="Amazify daemon is not running.",
            pid=0,
        )
        return 0

    request_daemon_stop(config)
    deadline = time.monotonic() + DAEMON_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            mark_daemon_state(
                config,
                status="stopped",
                message="Amazify daemon stopped.",
                pid=0,
            )
            emit("Amazify daemon stopped.")
            return 0
        time.sleep(0.25)

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        emit(f"Unable to stop Amazify daemon: {exc}", file=sys.stderr)
        return 1

    mark_daemon_state(
        config, status="stopped", message="Amazify daemon stopped.", pid=0
    )
    emit("Amazify daemon stopped.")
    return 0


def status_daemon_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create()
    state = read_daemon_state(config)
    pid = _coerce_int(state.get("pid")) or 0
    running = bool(pid and is_pid_running(pid))
    if not state:
        emit("Amazify daemon is not running.")
        return 1
    status = state.get("status") or "unknown"
    message = state.get("message") or ""
    emit(f"Amazify daemon: {'running' if running else 'stopped'}")
    emit(f"Status: {status}")
    if pid:
        emit(f"PID: {pid}")
    if running and state.get("bridge_url"):
        emit(f"Bridge: {state['bridge_url']}")
    if running and state.get("devtools_port"):
        emit(f"DevTools port: {state['devtools_port']}")
    if message:
        emit(f"Message: {message}")
    if state.get("updated_at"):
        emit(f"Updated: {state['updated_at']}")
    return 0 if running else 1


def start_daemon(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
    request_launch: bool = False,
) -> int:
    state = read_daemon_state(config)
    pid = _coerce_int(state.get("pid")) or 0
    if pid and is_pid_running(pid):
        if request_launch:
            request_daemon_launch(config)
            emit(f"Amazon Music launch requested through Amazify daemon PID {pid}.")
        else:
            emit(f"Amazify daemon is already running with PID {pid}.")
        return 0

    remove_daemon_stop_file(config)
    command = daemon_spawn_command(args, launch_on_start=request_launch)
    log_file = config.log_dir / "daemon-process.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200 | 0x08000000
    with log_file.open("ab") as log_stream:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=log_stream,
            cwd=str(Path.cwd()),
            close_fds=True,
            creationflags=flags,
        )

    deadline = time.monotonic() + DAEMON_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = read_daemon_state(config)
        pid = _coerce_int(state.get("pid")) or 0
        if pid and is_pid_running(pid):
            emit(f"Amazify daemon started with PID {pid}.")
            return 0
        time.sleep(0.25)

    emit("Amazify daemon start was requested, but it did not report ready yet.")
    emit(f"Daemon process log: {log_file}")
    return 0


def run_daemon(args: argparse.Namespace) -> int:
    daemon_mutex = acquire_daemon_mutex()
    if daemon_mutex is None:
        LOG.info("Another Amazify daemon already owns the launch supervisor mutex")
        return 0
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    log_file = setup_logging(config.log_dir, verbose=getattr(args, "verbose", False))
    LOG.info("Amazify launch supervisor starting. Logs: %s", log_file)
    remove_daemon_stop_file(config)
    remove_daemon_launch_file(config)
    plugin_manager = create_plugin_manager(config)
    app_updater = create_application_updater(config)
    bridge = LocalBridge(
        port=config.bridge_port,
        token=config.bridge_token,
        plugin_manager=plugin_manager,
    )
    bridge.start()

    stop_requested = False
    client: DevToolsClient | None = None
    launch_pending = bool(getattr(args, "launch_on_start", False))
    owned_devtools_port: int | None = None
    last_heartbeat = 0.0
    last_auto_attach = 0.0

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    mark_daemon_state(
        config,
        status="idle",
        message="Amazify daemon is ready.",
        log_file=log_file,
    )

    try:
        while not stop_requested and not config.daemon_stop_file.exists():
            launch_requested_now = consume_daemon_launch_request(config)
            launch_pending = launch_pending or launch_requested_now

            if client is not None:
                if launch_pending:
                    try:
                        focus_amazon_music()
                    except Exception:
                        LOG.debug("Unable to focus Amazon Music", exc_info=True)
                    launch_pending = False
                try:
                    client.pump(timeout=0.2)
                except DevToolsConnectionClosed as exc:
                    LOG.info("Amazon Music closed; daemon returning to idle: %s", exc)
                    client.close()
                    client = None
                    owned_devtools_port = None
                    mark_daemon_state(
                        config,
                        status="idle",
                        message="Amazify daemon is waiting for Amazon Music.",
                        log_file=log_file,
                    )
                except DevToolsError as exc:
                    LOG.info(
                        "DevTools connection ended; daemon returning to idle: %s", exc
                    )
                    client.close()
                    client = None
                    owned_devtools_port = None
                    mark_daemon_state(
                        config,
                        status="idle",
                        message="Amazify daemon is waiting for Amazon Music.",
                        log_file=log_file,
                    )
                except Exception as exc:
                    LOG.exception("Unexpected DevTools pump failure; returning to idle")
                    client.close()
                    client = None
                    owned_devtools_port = None
                    mark_daemon_state(
                        config,
                        status="error",
                        message=f"DevTools connection failed: {exc}",
                        log_file=log_file,
                    )
                if (
                    client is not None
                    and time.monotonic() - last_heartbeat >= DAEMON_HEARTBEAT_SECONDS
                ):
                    last_heartbeat = time.monotonic()
                    mark_daemon_state(
                        config,
                        status="connected",
                        message="Amazify is injected into Amazon Music.",
                        log_file=log_file,
                    )
                continue

            now = time.monotonic()
            connection: ConnectedTarget | None = None
            launch_started_without_existing_app = False
            try:
                if launch_pending:
                    launch_pending = False
                    launch_started_without_existing_app = not amazon_music_is_running()
                    mark_daemon_state(
                        config,
                        status="launching",
                        message="Launching or connecting to Amazon Music.",
                        log_file=log_file,
                    )
                    connection = connect_or_launch_result(
                        config,
                        connect_only=getattr(args, "connect_only", False),
                        prefer_known_ports=getattr(args, "devtools_port", None) is None,
                    )
                    if connection.launched_by_amazify:
                        owned_devtools_port = config.devtools_port
                elif now - last_auto_attach >= DAEMON_AUTO_ATTACH_SECONDS:
                    last_auto_attach = now
                    target = connect_to_known_devtools_port(
                        config, include_log_ports=False
                    )
                    if target is not None:
                        connection = ConnectedTarget(
                            target,
                            launched_by_amazify=config.devtools_port
                            == owned_devtools_port,
                        )

                if connection is not None:
                    client = inject_connection(
                        config,
                        plugin_manager,
                        connection,
                        app_updater=app_updater,
                    )
                    mark_daemon_state(
                        config,
                        status="connected",
                        message="Amazify is injected into Amazon Music.",
                        log_file=log_file,
                    )
            except (DevToolsError, LaunchError, OSError) as exc:
                if launch_started_without_existing_app:
                    owned_devtools_port = config.devtools_port
                LOG.exception("Amazify launch request failed")
                mark_daemon_state(
                    config,
                    status="error",
                    message=str(exc),
                    log_file=log_file,
                )
            except Exception:
                LOG.exception("Unexpected daemon attach failure; returning to idle")
                mark_daemon_state(
                    config,
                    status="idle",
                    message="Amazify daemon is waiting for Amazon Music.",
                    log_file=log_file,
                )

            if time.monotonic() - last_heartbeat >= DAEMON_HEARTBEAT_SECONDS:
                last_heartbeat = time.monotonic()
                if (
                    client is None
                    and read_daemon_state(config).get("status") != "error"
                ):
                    mark_daemon_state(
                        config,
                        status="idle",
                        message="Amazify daemon is waiting for Amazon Music.",
                        log_file=log_file,
                    )
            time.sleep(DAEMON_POLL_SECONDS)
    finally:
        if client is not None:
            try:
                client.evaluate(build_cleanup_script())
            except Exception:
                LOG.debug(
                    "Cleanup injection failed during daemon shutdown", exc_info=True
                )
            client.close()
        bridge.stop()
        mark_daemon_state(
            config, status="stopped", message="Amazify daemon stopped.", pid=0
        )
        remove_daemon_stop_file(config)
        remove_daemon_launch_file(config)
        release_daemon_mutex(daemon_mutex)
    return 0


def daemon_spawn_command(
    args: argparse.Namespace,
    *,
    launch_on_start: bool = False,
) -> list[str]:
    entry = python_entry_command()
    command = [*entry, "daemon", "run"]
    for option in ["devtools_port", "bridge_port", "manual_launcher"]:
        value = getattr(args, option, None)
        if value is not None:
            command.extend([f"--{option.replace('_', '-')}", str(value)])
    if getattr(args, "connect_only", False):
        command.append("--connect-only")
    if launch_on_start:
        command.append("--launch-on-start")
    if getattr(args, "verbose", False):
        command.insert(1 if getattr(sys, "frozen", False) else len(entry), "--verbose")
    return command


def python_entry_command() -> list[str]:
    if getattr(sys, "frozen", False):
        sibling_windowed = (
            Path(sys.executable).resolve().parent / "amazifyw" / "amazifyw.exe"
        )
        if sibling_windowed.exists():
            return [str(sibling_windowed)]
        return [sys.executable]
    return [sys.executable, "-m", "amazify"]


def mark_daemon_state(
    config: RuntimeConfig,
    *,
    status: str,
    message: str,
    log_file: Path | None = None,
    pid: int | None = None,
) -> None:
    data = {
        "version": DAEMON_STATE_VERSION,
        "pid": os.getpid() if pid is None else pid,
        "status": status,
        "message": message,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "devtools_port": config.devtools_port,
        "bridge_port": config.bridge_port,
        "bridge_url": config.bridge_url,
    }
    if log_file is not None:
        data["log_file"] = str(log_file)
    try:
        config.daemon_state_file.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        LOG.debug("Unable to write daemon state file: %s", exc)


def read_daemon_state(config: RuntimeConfig) -> dict[str, object]:
    try:
        data = json.loads(config.daemon_state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str)}


def request_daemon_stop(config: RuntimeConfig) -> None:
    try:
        config.daemon_stop_file.write_text(
            time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.debug("Unable to write daemon stop file: %s", exc)


def request_daemon_launch(config: RuntimeConfig) -> None:
    payload = {
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "request_id": f"{os.getpid()}-{time.time_ns()}",
    }
    temporary = config.daemon_launch_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(config.daemon_launch_file)


def consume_daemon_launch_request(config: RuntimeConfig) -> bool:
    try:
        config.daemon_launch_file.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        LOG.debug("Unable to consume daemon launch request: %s", exc)
        return False


def remove_daemon_launch_file(config: RuntimeConfig) -> None:
    try:
        config.daemon_launch_file.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        LOG.debug("Unable to remove daemon launch request: %s", exc)


def remove_daemon_stop_file(config: RuntimeConfig) -> None:
    try:
        config.daemon_stop_file.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        LOG.debug("Unable to remove daemon stop file: %s", exc)


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information,
        False,
        int(pid),
    )
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(
            handle, ctypes.byref(exit_code)
        ):
            return False
        return exit_code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def acquire_daemon_mutex() -> int | None:
    if os.name != "nt":
        return 0
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
    if not handle:
        raise OSError("Unable to create Amazify daemon mutex")
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def release_daemon_mutex(handle: int) -> None:
    if os.name == "nt" and handle:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


def connect_or_launch(
    config: RuntimeConfig,
    *,
    connect_only: bool,
    prefer_known_ports: bool = True,
) -> Target:
    return connect_or_launch_result(
        config,
        connect_only=connect_only,
        prefer_known_ports=prefer_known_ports,
    ).target


def connect_or_launch_result(
    config: RuntimeConfig,
    *,
    connect_only: bool,
    prefer_known_ports: bool = True,
) -> ConnectedTarget:
    if prefer_known_ports:
        target = connect_to_known_devtools_port(config)
        if target is not None:
            return ConnectedTarget(target, launched_by_amazify=False)

    if connect_only:
        LOG.info(
            "Connecting to existing DevTools target on port %s", config.devtools_port
        )
        return ConnectedTarget(
            DevToolsHttp(config.devtools_port).wait_for_amazon_music_target(
                timeout_seconds=30
            ),
            launched_by_amazify=False,
        )

    if amazon_music_is_running():
        raise LaunchError(
            "Amazon Music is already running without an accessible DevTools endpoint. "
            "Close it once, then launch Amazon Music (Amazify) again."
        )

    if prefer_known_ports:
        config.devtools_port = find_free_local_port()
    http = DevToolsHttp(config.devtools_port)
    candidates = runtime_launch_candidates(config.manual_launcher)
    if not candidates:
        raise LaunchError("No Amazon Music launch candidates were discovered")

    last_error: Exception | None = None
    for candidate in candidates:
        timeout_seconds = (
            AUMID_TARGET_TIMEOUT_SECONDS
            if candidate.kind == "aumid"
            else EXE_TARGET_TIMEOUT_SECONDS
        )
        try:
            launch_candidate(candidate, config.devtools_port)
            return ConnectedTarget(
                http.wait_for_amazon_music_target(timeout_seconds=timeout_seconds),
                launched_by_amazify=True,
            )
        except (LaunchError, DevToolsError, OSError) as exc:
            LOG.info("Launch candidate failed: %s (%s)", candidate.label, exc)
            last_error = exc
    raise LaunchError(
        "No launch candidate produced an Amazon Music DevTools target "
        f"on port {config.devtools_port}: {last_error}"
    )


def connect_to_known_devtools_port(
    config: RuntimeConfig,
    *,
    include_log_ports: bool = True,
) -> Target | None:
    ports: list[int] = []
    for port in running_amazon_music_devtools_ports():
        _append_unique_port(ports, port)
    _append_unique_port(ports, config.devtools_port)
    if include_log_ports:
        for port in recent_devtools_ports(config):
            _append_unique_port(ports, port)
    ports = ports[:KNOWN_PORT_LIMIT]
    if not ports:
        return None

    targets: dict[int, Target] = {}

    def probe(port: int) -> tuple[int, Target | None]:
        try:
            http = DevToolsHttp(port)
            http.request_timeout = 0.25
            target = http.wait_for_amazon_music_target(
                timeout_seconds=KNOWN_PORT_PROBE_TIMEOUT_SECONDS
            )
        except DevToolsError:
            return port, None
        return port, target

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(ports), 8)
    ) as executor:
        for port, target in executor.map(probe, ports):
            if target is not None:
                targets[port] = target

    for port in ports:
        target = targets.get(port)
        if target is None:
            continue
        config.devtools_port = port
        LOG.info("Reusing existing Amazon Music DevTools target on port %s", port)
        return target
    return None


def remember_devtools_port(config: RuntimeConfig) -> None:
    data = {
        "last_port": config.devtools_port,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        config.devtools_state_file.write_text(
            json.dumps(data, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.debug("Unable to write DevTools state file: %s", exc)


def show_first_run_welcome(config: RuntimeConfig) -> bool:
    if config.welcome_state_file.exists():
        return False
    emit(
        "Welcome to Amazify.\n"
        "Tip: use the Amazon Music (Amazify) shortcut from the installer so "
        "Amazon Music opens through Amazify with DevTools enabled automatically.\n"
        "Use the installer shortcut options to add Desktop or taskbar shortcuts.\n"
    )
    try:
        config.welcome_state_file.write_text(
            json.dumps(
                {
                    "version": WELCOME_STATE_VERSION,
                    "shown_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.debug("Unable to write welcome state file: %s", exc)
    return True


def recent_devtools_ports(config: RuntimeConfig) -> list[int]:
    ports: list[int] = []
    try:
        data = json.loads(config.devtools_state_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _append_unique_port(ports, data.get("last_port"))
    except (OSError, json.JSONDecodeError):
        pass

    log_file = config.log_dir / "amazify.log"
    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        match = DEVTOOLS_PORT_PATTERN.search(line)
        if match:
            _append_unique_port(ports, match.group(1))
        if len(ports) >= KNOWN_PORT_LIMIT:
            break
    return ports


def _append_unique_port(ports: list[int], value: object) -> None:
    port = _coerce_int(value)
    if port is None:
        return
    if not 0 < port <= 65535:
        return
    if port not in ports:
        ports.append(port)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def list_candidates(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(manual_launcher=args.manual_launcher)
    setup_logging(config.log_dir, verbose=getattr(args, "verbose", False))
    candidates = discover_launch_candidates(args.manual_launcher)
    if not candidates:
        emit("No Amazon Music launch candidates found.")
        return 1
    for index, candidate in enumerate(candidates, start=1):
        emit(f"{index}. [{candidate.kind}] {candidate.label}: {candidate.value}")
    return 0


def shortcuts_command(args: argparse.Namespace) -> int:
    from .shortcuts import install_amazify_shortcuts, remove_amazify_shortcuts

    action = getattr(args, "shortcuts_action", None)
    if action == "install":
        target = (
            Path(getattr(args, "target_exe", "")).expanduser()
            if getattr(args, "target_exe", None)
            else Path(sys.executable)
        )
        result = install_amazify_shortcuts(
            target,
            start_menu=bool(getattr(args, "start_menu", False)),
            desktop=bool(getattr(args, "desktop", False)),
            taskbar=bool(getattr(args, "taskbar", False)),
        )
        for shortcut in result.created:
            emit(f"Created shortcut: {shortcut}")
        for warning in result.warnings:
            emit(f"Shortcut warning: {warning}")
        return 0
    if action == "remove":
        result = remove_amazify_shortcuts()
        for shortcut in result.removed:
            emit(f"Removed shortcut: {shortcut}")
        for warning in result.warnings:
            emit(f"Shortcut warning: {warning}")
        return 0
    emit("Choose a shortcuts command: install or remove.", file=sys.stderr)
    return 2


def update_command(args: argparse.Namespace) -> int:
    action = getattr(args, "update_action", None)
    if action not in {"check", "install"}:
        emit("Choose an update command: check or install.", file=sys.stderr)
        return 2

    config = RuntimeConfig.create()
    updater = create_application_updater(config)
    try:
        status = updater.check_now()
    except UpdateError as exc:
        emit(f"Amazify update check failed: {exc}", file=sys.stderr)
        return 1

    if action == "check":
        if bool(getattr(args, "json", False)):
            emit(json.dumps(status, sort_keys=True))
        elif status["updateAvailable"]:
            emit(
                f"Amazify {status['latestVersion']} is available "
                f"(installed: {status['currentVersion']})."
            )
            emit(f"Release: {status['releaseUrl']}")
        else:
            emit(f"Amazify {status['currentVersion']} is up to date.")
        return 0

    if not status["updateAvailable"]:
        emit(f"Amazify {status['currentVersion']} is already up to date.")
        return 0
    if not bool(getattr(args, "yes", False)):
        try:
            answer = input(
                f"Download and launch the verified Amazify "
                f"{status['latestVersion']} installer? [y/N] "
            )
        except (EOFError, OSError):
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            emit("Amazify update cancelled.")
            return 0
    try:
        updater.install_now()
    except UpdateError as exc:
        emit(f"Amazify update failed: {exc}", file=sys.stderr)
        return 1
    emit(
        f"Verified Amazify {status['latestVersion']} installer launched. "
        "Complete the installer to finish updating."
    )
    return 0


def emit(message: str = "", *, file: TextIO | None = None) -> None:
    stream = file if file is not None else sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream)
    except (AttributeError, OSError, ValueError):
        return
