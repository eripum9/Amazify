from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from .bridge import LocalBridge
from .config import RuntimeConfig
from .devtools import DevToolsClient, DevToolsConnectionClosed, DevToolsError, DevToolsHttp
from .launcher import LaunchError, discover_launch_candidates, launch_candidate
from .logging_setup import setup_logging
from .native_bridge import NativeBindingBridge
from .plugin_manager import PluginManager
from .runtime import build_cleanup_script, build_runtime_script


LOG = logging.getLogger(__name__)


WELCOME_STATE_VERSION = 1
DAEMON_STATE_VERSION = 1
DAEMON_START_TIMEOUT_SECONDS = 8
DAEMON_STOP_TIMEOUT_SECONDS = 10
DAEMON_HEARTBEAT_SECONDS = 2
DAEMON_RETRY_DELAY_SECONDS = 4
AUMID_LAUNCH_ATTEMPTS = 3
AUMID_TARGET_TIMEOUT_SECONDS = 20
EXE_TARGET_TIMEOUT_SECONDS = 15
RETRY_DELAY_SECONDS = 2
KNOWN_PORT_PROBE_TIMEOUT_SECONDS = 1.25
KNOWN_PORT_LIMIT = 8
DEVTOOLS_PORT_PATTERN = re.compile(r"(?:DevTools port:|with DevTools port)\s*(\d+)")


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
    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazify",
        description="Amazify Amazon Music runtime customization prototype.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

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
    daemon_start_parser = daemon_subparsers.add_parser("start", help="Start the daemon.")
    add_launch_arguments(daemon_start_parser)
    daemon_subparsers.add_parser("stop", help="Stop the daemon.")
    daemon_subparsers.add_parser("status", help="Show daemon status.")
    daemon_run_parser = daemon_subparsers.add_parser(
        "run",
        help="Run the daemon worker in the current process.",
    )
    add_launch_arguments(daemon_run_parser)

    shortcuts_parser = subparsers.add_parser(
        "shortcuts",
        help="Install or remove Amazify launch shortcuts.",
    )
    shortcuts_subparsers = shortcuts_parser.add_subparsers(dest="shortcuts_action")
    shortcuts_install = shortcuts_subparsers.add_parser("install", help="Install shortcuts.")
    shortcuts_install.add_argument("--start-menu", action="store_true")
    shortcuts_install.add_argument("--desktop", action="store_true")
    shortcuts_install.add_argument("--taskbar", action="store_true")
    shortcuts_install.add_argument("--target-exe", default=None)
    shortcuts_subparsers.add_parser("remove", help="Remove shortcuts.")

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


def run(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    show_first_run_welcome(config)
    if getattr(args, "foreground", False) or getattr(args, "once", False):
        return run_foreground(args, config=config, daemon_mode=False)
    return start_daemon(args, config=config)


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

    plugin_manager = PluginManager(config.plugin_dir, config.plugin_state_file)

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
        target = connect_or_launch(
            config,
            connect_only=getattr(args, "connect_only", False),
            prefer_known_ports=not explicit_devtools_port,
        )
        client = DevToolsClient(target)
        client.connect()
        native_bridge = NativeBindingBridge(client, plugin_manager)
        native_bridge.install()
        probe = client.probe_amazon_music()
        remember_devtools_port(config)
        LOG.info(
            "Connected to Amazon Music target: title=%r url=%r",
            probe.get("title"),
            probe.get("href"),
        )
        client.evaluate(build_cleanup_script())
        result = client.evaluate(
            build_runtime_script(
                bridge_url=config.bridge_url,
                bridge_token=config.bridge_token,
                plugins=plugin_manager.runtime_snapshot(),
                catalog_plugins=plugin_manager.catalog_payload()["plugins"],
            )
        )
        LOG.info("Injected Amazify runtime: %s", result)
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
            LOG.warning("--once exits immediately; bridge-backed UI commands will stop working.")
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
            if daemon_mode and time.monotonic() - last_heartbeat >= DAEMON_HEARTBEAT_SECONDS:
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
    pid = int(state.get("pid") or 0) if state else 0
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

    mark_daemon_state(config, status="stopped", message="Amazify daemon stopped.", pid=0)
    emit("Amazify daemon stopped.")
    return 0


def status_daemon_command(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create()
    state = read_daemon_state(config)
    pid = int(state.get("pid") or 0) if state else 0
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


def start_daemon(args: argparse.Namespace, *, config: RuntimeConfig) -> int:
    state = read_daemon_state(config)
    pid = int(state.get("pid") or 0) if state else 0
    if pid and is_pid_running(pid):
        emit(f"Amazify daemon is already running with PID {pid}.")
        return 0

    remove_daemon_stop_file(config)
    command = daemon_spawn_command(args)
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
        pid = int(state.get("pid") or 0) if state else 0
        if pid and is_pid_running(pid):
            emit(f"Amazify daemon started with PID {pid}.")
            return 0
        time.sleep(0.25)

    emit("Amazify daemon start was requested, but it did not report ready yet.")
    emit(f"Daemon process log: {log_file}")
    return 0


def run_daemon(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    config.log_dir.mkdir(parents=True, exist_ok=True)
    remove_daemon_stop_file(config)
    mark_daemon_state(config, status="starting", message="Amazify daemon is starting.")

    while not config.daemon_stop_file.exists():
        exit_code = run_foreground(args, config=config, daemon_mode=True)
        if config.daemon_stop_file.exists() or exit_code == 0:
            break
        mark_daemon_state(
            config,
            status="waiting",
            message=f"Amazon Music is not ready. Retrying in {DAEMON_RETRY_DELAY_SECONDS}s.",
        )
        deadline = time.monotonic() + DAEMON_RETRY_DELAY_SECONDS
        while time.monotonic() < deadline:
            if config.daemon_stop_file.exists():
                break
            time.sleep(0.25)

    mark_daemon_state(config, status="stopped", message="Amazify daemon stopped.", pid=0)
    remove_daemon_stop_file(config)
    return 0


def daemon_spawn_command(args: argparse.Namespace) -> list[str]:
    entry = python_entry_command()
    command = [*entry, "daemon", "run"]
    for option in ["devtools_port", "bridge_port", "manual_launcher"]:
        value = getattr(args, option, None)
        if value is not None:
            command.extend([f"--{option.replace('_', '-')}", str(value)])
    if getattr(args, "connect_only", False):
        command.append("--connect-only")
    if getattr(args, "verbose", False):
        command.insert(1 if getattr(sys, "frozen", False) else len(entry), "--verbose")
    return command


def python_entry_command() -> list[str]:
    if getattr(sys, "frozen", False):
        sibling_windowed = Path(sys.executable).resolve().parent / "amazifyw" / "amazifyw.exe"
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
        config.daemon_state_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        LOG.debug("Unable to write daemon state file: %s", exc)


def read_daemon_state(config: RuntimeConfig) -> dict[str, object]:
    try:
        data = json.loads(config.daemon_state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def request_daemon_stop(config: RuntimeConfig) -> None:
    try:
        config.daemon_stop_file.write_text(
            time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        LOG.debug("Unable to write daemon stop file: %s", exc)


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
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def connect_or_launch(
    config: RuntimeConfig,
    *,
    connect_only: bool,
    prefer_known_ports: bool = True,
) -> object:
    if prefer_known_ports:
        target = connect_to_known_devtools_port(config)
        if target is not None:
            return target

    http = DevToolsHttp(config.devtools_port)
    if connect_only:
        LOG.info("Connecting to existing DevTools target on port %s", config.devtools_port)
        return http.wait_for_amazon_music_target(timeout_seconds=30)

    candidates = discover_launch_candidates(config.manual_launcher)
    if not candidates:
        raise LaunchError("No Amazon Music launch candidates were discovered")

    last_error: Exception | None = None
    for candidate in candidates:
        attempts = AUMID_LAUNCH_ATTEMPTS if candidate.kind == "aumid" else 1
        timeout_seconds = (
            AUMID_TARGET_TIMEOUT_SECONDS
            if candidate.kind == "aumid"
            else EXE_TARGET_TIMEOUT_SECONDS
        )
        for attempt in range(1, attempts + 1):
            try:
                launch_candidate(candidate, config.devtools_port)
                return http.wait_for_amazon_music_target(timeout_seconds=timeout_seconds)
            except (LaunchError, DevToolsError, OSError) as exc:
                LOG.info(
                    "Launch candidate failed: %s attempt %s/%s (%s)",
                    candidate.label,
                    attempt,
                    attempts,
                    exc,
                )
                last_error = exc
                if attempt < attempts:
                    time.sleep(RETRY_DELAY_SECONDS)
    raise LaunchError(
        "No launch candidate produced an Amazon Music DevTools target "
        f"on port {config.devtools_port}: {last_error}"
    )


def connect_to_known_devtools_port(config: RuntimeConfig) -> object | None:
    for port in recent_devtools_ports(config):
        try:
            target = DevToolsHttp(port).wait_for_amazon_music_target(
                timeout_seconds=KNOWN_PORT_PROBE_TIMEOUT_SECONDS
            )
        except DevToolsError:
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
    try:
        port = int(value)
    except (TypeError, ValueError):
        return
    if not 0 < port <= 65535:
        return
    if port not in ports:
        ports.append(port)


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


def emit(message: str = "", *, file: object | None = None) -> None:
    stream = file if file is not None else sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream)
    except (AttributeError, OSError, ValueError):
        return
