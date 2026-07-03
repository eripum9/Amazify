from __future__ import annotations

import argparse
import json
import logging
import re
import signal
import sys
import time

from .bridge import LocalBridge
from .config import RuntimeConfig
from .devtools import DevToolsClient, DevToolsError, DevToolsHttp
from .launcher import LaunchError, discover_launch_candidates, launch_candidate
from .logging_setup import setup_logging
from .native_bridge import NativeBindingBridge
from .plugin_manager import PluginManager
from .runtime import build_cleanup_script, build_runtime_script


LOG = logging.getLogger(__name__)


WELCOME_STATE_VERSION = 1
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
    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazify",
        description="Amazify Amazon Music runtime customization prototype.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Launch/connect and inject Amazify.")
    run_parser.add_argument(
        "--devtools-port",
        type=int,
        default=None,
        help="Use a specific DevTools port instead of a random free port.",
    )
    run_parser.add_argument(
        "--bridge-port",
        type=int,
        default=None,
        help="Use a specific localhost bridge port instead of a random free port.",
    )
    run_parser.add_argument(
        "--manual-launcher",
        default=None,
        help="Manual Amazon Music executable path or AUMID.",
    )
    run_parser.add_argument(
        "--connect-only",
        action="store_true",
        help="Do not launch Amazon Music; connect to an existing DevTools target.",
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

    return parser


def run(args: argparse.Namespace) -> int:
    config = RuntimeConfig.create(
        devtools_port=getattr(args, "devtools_port", None),
        bridge_port=getattr(args, "bridge_port", None),
        manual_launcher=getattr(args, "manual_launcher", None),
    )
    show_first_run_welcome(config)
    log_file = setup_logging(config.log_dir, verbose=args.verbose)
    LOG.info("Amazify starting. Logs: %s", log_file)

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
        print("Amazify injected into Amazon Music.")
        print(f"DevTools port: {config.devtools_port}")
        print(f"Bridge: {config.bridge_url}")
        print(f"Plugins: {config.plugin_dir}")
        print(f"Logs: {log_file}")

        if getattr(args, "once", False):
            LOG.warning("--once exits immediately; bridge-backed UI commands will stop working.")
            return 0

        while not stop_requested:
            try:
                client.pump(timeout=0.5)
            except DevToolsError as exc:
                LOG.info("DevTools event pump stopped: %s", exc)
                time.sleep(0.5)
        return 0
    except (DevToolsError, LaunchError, OSError) as exc:
        LOG.exception("Amazify failed")
        print(f"Amazify failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            try:
                client.evaluate(build_cleanup_script())
            except Exception:
                LOG.debug("Cleanup injection failed during shutdown", exc_info=True)
            client.close()
        bridge.stop()


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
    print(
        "Welcome to Amazify.\n"
        "Tip: use the Amazon Music (Amazify) shortcut from the installer so "
        "Amazon Music opens through Amazify with DevTools enabled automatically.\n"
        "Run AmazifySetup.exe --desktop-shortcut or --taskbar-shortcut to add "
        "more launch shortcuts later.\n"
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
        print("No Amazon Music launch candidates found.")
        return 1
    for index, candidate in enumerate(candidates, start=1):
        print(f"{index}. [{candidate.kind}] {candidate.label}: {candidate.value}")
    return 0
