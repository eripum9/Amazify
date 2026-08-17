from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .config import DEVTOOLS_HOST
from .plugin_manager import PluginError, PluginManager


LOG = logging.getLogger(__name__)
BridgeCommandHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


class LocalBridge:
    def __init__(
        self,
        *,
        port: int,
        token: str,
        plugin_manager: PluginManager,
        command_handler: BridgeCommandHandler | None = None,
    ) -> None:
        self.port = port
        self.token = token
        self.plugin_manager = plugin_manager
        self.command_handler = command_handler
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((DEVTOOLS_HOST, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="amazify-bridge",
            daemon=True,
        )
        self._thread.start()
        LOG.info("Local bridge listening on http://%s:%s", DEVTOOLS_HOST, self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AmazifyBridge/0.1"

            def log_message(self, format: str, *args: object) -> None:
                LOG.debug("Bridge: " + format, *args)

            def do_OPTIONS(self) -> None:
                self._send_empty(HTTPStatus.NO_CONTENT)

            def do_GET(self) -> None:
                if self.path_only == "/health":
                    self._send_json({"ok": True, "app": "Amazify"})
                    return
                if self.path_only == "/state":
                    if not self._authorized():
                        self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    self._send_json(self._state_payload())
                    return
                if self.path_only == "/plugins":
                    if not self._authorized():
                        self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    self._send_json({"plugins": bridge.plugin_manager.public_plugins()})
                    return
                if self.path_only == "/catalog":
                    if not self._authorized():
                        self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    force = "refresh=1" in self.path or "force=1" in self.path
                    self._send_json(
                        {
                            "ok": True,
                            "catalog": bridge.plugin_manager.catalog_payload(
                                force_refresh=force
                            ),
                        }
                    )
                    return
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if not self._authorized():
                    self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    payload = self._read_json()
                    if self.path_only == "/plugins/enable":
                        plugin_id = str(payload.get("pluginId", ""))
                        bridge.plugin_manager.enable(plugin_id)
                        self._send_json(self._state_payload())
                        return
                    if self.path_only == "/plugins/disable":
                        plugin_id = str(payload.get("pluginId", ""))
                        bridge.plugin_manager.disable(plugin_id)
                        self._send_json(self._state_payload())
                        return
                    if self.path_only == "/plugins/install":
                        plugin_id = str(payload.get("pluginId", ""))
                        bridge.plugin_manager.install_from_catalog(plugin_id)
                        self._send_json(self._state_payload(force_catalog_refresh=True))
                        return
                    if self.path_only == "/command":
                        name = str(payload.get("name", ""))
                        command_payload = payload.get("payload", {})
                        if not isinstance(command_payload, dict):
                            command_payload = {}
                        result = bridge._handle_command(name, command_payload)
                        self._send_json(result)
                        return
                except PluginError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            @property
            def path_only(self) -> str:
                return self.path.split("?", 1)[0]

            def _authorized(self) -> bool:
                return self.headers.get("X-Amazify-Token") == bridge.token

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length).decode("utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                return data

            def _state_payload(self, *, force_catalog_refresh: bool = False) -> dict[str, Any]:
                catalog = bridge.plugin_manager.catalog_payload(
                    force_refresh=force_catalog_refresh
                )
                return {
                    "ok": True,
                    "bridge": {
                        "host": DEVTOOLS_HOST,
                        "port": bridge.port,
                    },
                    "plugins": bridge.plugin_manager.public_plugins(),
                    "runtimePlugins": bridge.plugin_manager.runtime_snapshot(),
                    "catalogPlugins": catalog["plugins"],
                    "catalogError": catalog["error"],
                    "catalogUrl": catalog["url"],
                }

            def _send_empty(self, status: HTTPStatus) -> None:
                self.send_response(status)
                self._send_headers("text/plain")
                self.end_headers()

            def _send_json(
                self,
                data: dict[str, Any],
                status: HTTPStatus = HTTPStatus.OK,
            ) -> None:
                encoded = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self._send_headers("application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_headers(self, content_type: str) -> None:
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-Amazify-Token",
                )
                self.send_header(
                    "Access-Control-Allow-Methods",
                    "GET, POST, OPTIONS",
                )
                self.send_header("Access-Control-Allow-Private-Network", "true")

        return Handler

    def _handle_command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name == "plugins.disableAll":
            self.plugin_manager.disable_all()
            catalog = self.plugin_manager.catalog_payload()
            return {
                "ok": True,
                "plugins": self.plugin_manager.public_plugins(),
                "runtimePlugins": self.plugin_manager.runtime_snapshot(),
                "catalogPlugins": catalog["plugins"],
                "catalogError": catalog["error"],
                "catalogUrl": catalog["url"],
            }
        if name == "catalog.refresh":
            catalog = self.plugin_manager.catalog_payload(force_refresh=True)
            return {
                "ok": True,
                "plugins": self.plugin_manager.public_plugins(),
                "runtimePlugins": self.plugin_manager.runtime_snapshot(),
                "catalogPlugins": catalog["plugins"],
                "catalogError": catalog["error"],
                "catalogUrl": catalog["url"],
            }
        if name == "plugins.install":
            self.plugin_manager.install_from_catalog(str(payload.get("pluginId", "")))
            catalog = self.plugin_manager.catalog_payload(force_refresh=True)
            return {
                "ok": True,
                "plugins": self.plugin_manager.public_plugins(),
                "runtimePlugins": self.plugin_manager.runtime_snapshot(),
                "catalogPlugins": catalog["plugins"],
                "catalogError": catalog["error"],
                "catalogUrl": catalog["url"],
            }
        if self.command_handler:
            return self.command_handler(name, payload)
        return {"ok": False, "error": f"Unknown command: {name}"}
