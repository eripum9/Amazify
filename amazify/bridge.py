from __future__ import annotations

import hmac
import json
import logging
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import DEVTOOLS_HOST
from .devtools import exact_https_origin
from .plugin_manager import PluginError, PluginManager

LOG = logging.getLogger(__name__)
TOKEN_HEADER = "X-Amazify-Token"
MAX_REQUEST_BYTES = 16 * 1024
ALLOWED_REQUEST_HEADERS = frozenset({"content-type", TOKEN_HEADER.lower()})
ALLOWED_BRIDGE_COMMANDS = frozenset({"catalog.refresh", "plugins.disableAll"})


class BridgeRequestError(ValueError):
    def __init__(
        self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST
    ) -> None:
        super().__init__(message)
        self.status = status


class LocalBridge:
    def __init__(
        self,
        *,
        port: int,
        token: str,
        plugin_manager: PluginManager,
    ) -> None:
        self.port = port
        self.token = token
        self.plugin_manager = plugin_manager
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._operation_lock = threading.RLock()

    def start(self) -> None:
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((DEVTOOLS_HOST, self.port), handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
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
                if not self._require_trusted_request(require_origin=True):
                    return
                requested_method = str(
                    self.headers.get("Access-Control-Request-Method") or ""
                ).upper()
                if requested_method not in {"GET", "POST"}:
                    self._send_json(
                        {"error": "preflight_method_not_allowed"},
                        HTTPStatus.FORBIDDEN,
                    )
                    return
                requested_headers = {
                    header.strip().lower()
                    for header in str(
                        self.headers.get("Access-Control-Request-Headers") or ""
                    ).split(",")
                    if header.strip()
                }
                if not requested_headers.issubset(ALLOWED_REQUEST_HEADERS):
                    self._send_json(
                        {"error": "preflight_headers_not_allowed"},
                        HTTPStatus.FORBIDDEN,
                    )
                    return
                self._send_empty(HTTPStatus.NO_CONTENT)

            def do_GET(self) -> None:
                if self.path_only == "/health":
                    if not self._require_trusted_request(require_origin=False):
                        return
                    self._send_json({"ok": True, "app": "Amazify"})
                    return
                if not self._require_trusted_request(require_origin=True):
                    return
                if not self._authorized():
                    self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                if self.path_only == "/state":
                    self._send_json(self._state_payload())
                    return
                if self.path_only == "/plugins":
                    with bridge._operation_lock:
                        plugins = bridge.plugin_manager.public_plugins()
                    self._send_json({"plugins": plugins})
                    return
                if self.path_only == "/catalog":
                    query = urllib.parse.parse_qs(
                        urllib.parse.urlsplit(self.path).query,
                        keep_blank_values=True,
                    )
                    force = query.get("refresh") == ["1"] or query.get("force") == ["1"]
                    with bridge._operation_lock:
                        catalog = bridge.plugin_manager.catalog_payload(
                            force_refresh=force
                        )
                    self._send_json(
                        {
                            "ok": True,
                            "catalog": catalog,
                        }
                    )
                    return
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:
                if not self._require_trusted_request(require_origin=True):
                    return
                if not self._authorized():
                    self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    payload = self._read_json()
                    with bridge._operation_lock:
                        if self.path_only == "/plugins/enable":
                            plugin_id = str(payload.get("pluginId", ""))
                            bridge.plugin_manager.enable(plugin_id)
                            result = self._state_payload()
                        elif self.path_only == "/plugins/disable":
                            plugin_id = str(payload.get("pluginId", ""))
                            bridge.plugin_manager.disable(plugin_id)
                            result = self._state_payload()
                        elif self.path_only == "/plugins/install":
                            plugin_id = str(payload.get("pluginId", ""))
                            bridge.plugin_manager.install_from_catalog(plugin_id)
                            result = self._state_payload(force_catalog_refresh=True)
                        elif self.path_only == "/command":
                            name = str(payload.get("name", ""))
                            command_payload = payload.get("payload", {})
                            if not isinstance(command_payload, dict):
                                raise BridgeRequestError(
                                    "Command payload must be an object"
                                )
                            result = bridge._handle_command(name, command_payload)
                        else:
                            self._send_json(
                                {"error": "not_found"}, HTTPStatus.NOT_FOUND
                            )
                            return
                    self._send_json(result)
                    return
                except BridgeRequestError as exc:
                    self.close_connection = True
                    self._send_json({"error": str(exc)}, exc.status)
                    return
                except PluginError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                except Exception:
                    LOG.exception("Bridge request failed")
                    self._send_json(
                        {"error": "internal_error"},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

            @property
            def path_only(self) -> str:
                return self.path.split("?", 1)[0]

            def _authorized(self) -> bool:
                supplied_values = self.headers.get_all(TOKEN_HEADER) or []
                supplied = str(supplied_values[0]) if len(supplied_values) == 1 else ""
                return bool(
                    supplied
                    and bridge.token
                    and hmac.compare_digest(supplied, bridge.token)
                )

            @property
            def allowed_origin(self) -> str:
                origins = self.headers.get_all("Origin") or []
                if len(origins) != 1:
                    return ""
                return exact_https_origin(str(origins[0]))

            def _require_trusted_request(self, *, require_origin: bool) -> bool:
                if not self._valid_loopback_host():
                    self._send_json({"error": "host_not_allowed"}, HTTPStatus.FORBIDDEN)
                    return False
                supplied_origin = str(self.headers.get("Origin") or "")
                if require_origin and not self.allowed_origin:
                    self._send_json(
                        {"error": "origin_not_allowed"}, HTTPStatus.FORBIDDEN
                    )
                    return False
                if supplied_origin and not self.allowed_origin:
                    self._send_json(
                        {"error": "origin_not_allowed"}, HTTPStatus.FORBIDDEN
                    )
                    return False
                return True

            def _valid_loopback_host(self) -> bool:
                hosts = self.headers.get_all("Host") or []
                if len(hosts) != 1:
                    return False
                raw_host = str(hosts[0])
                if not raw_host or any(character.isspace() for character in raw_host):
                    return False
                try:
                    parsed = urllib.parse.urlsplit(f"//{raw_host}")
                    port = parsed.port
                except ValueError:
                    return False
                return bool(
                    (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
                    and port == bridge.port
                    and not parsed.username
                    and not parsed.password
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                )

            def _read_json(self) -> dict[str, Any]:
                if self.headers.get("Transfer-Encoding"):
                    raise BridgeRequestError("Transfer-Encoding is not supported")
                content_type = str(self.headers.get("Content-Type") or "")
                if content_type.split(";", 1)[0].strip().lower() != "application/json":
                    raise BridgeRequestError("Content-Type must be application/json")
                content_lengths = self.headers.get_all("Content-Length") or []
                if len(content_lengths) != 1:
                    raise BridgeRequestError("Exactly one Content-Length is required")
                try:
                    length = int(content_lengths[0])
                except (TypeError, ValueError) as exc:
                    raise BridgeRequestError("Invalid Content-Length") from exc
                if length < 0:
                    raise BridgeRequestError("Invalid Content-Length")
                if length > MAX_REQUEST_BYTES:
                    raise BridgeRequestError(
                        "Request body is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                    )
                raw = self.rfile.read(length) if length else b"{}"
                if len(raw) != length:
                    raise BridgeRequestError("Request body ended unexpectedly")
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BridgeRequestError("Invalid JSON") from exc
                if not isinstance(data, dict):
                    raise BridgeRequestError("JSON body must be an object")
                return data

            def _state_payload(
                self, *, force_catalog_refresh: bool = False
            ) -> dict[str, Any]:
                with bridge._operation_lock:
                    catalog = (
                        bridge.plugin_manager.catalog_payload(force_refresh=True)
                        if force_catalog_refresh
                        else bridge.plugin_manager.cached_catalog_payload()
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
                self._send_headers("text/plain; charset=utf-8")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _send_json(
                self,
                data: dict[str, Any],
                status: HTTPStatus = HTTPStatus.OK,
            ) -> None:
                encoded = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self._send_headers("application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_headers(self, content_type: str) -> None:
                self.send_header("Content-Type", content_type)
                if self.allowed_origin:
                    self.send_header("Access-Control-Allow-Origin", self.allowed_origin)
                    self.send_header(
                        "Vary",
                        "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
                    )
                    self.send_header(
                        "Access-Control-Allow-Headers",
                        f"Content-Type, {TOKEN_HEADER}",
                    )
                    self.send_header(
                        "Access-Control-Allow-Methods", "GET, POST, OPTIONS"
                    )
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")

        return Handler

    def _handle_command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._operation_lock:
            if name not in ALLOWED_BRIDGE_COMMANDS:
                return {"ok": False, "error": f"Command not allowed: {name}"}
            if name == "plugins.disableAll":
                self.plugin_manager.disable_all()
                catalog = self.plugin_manager.cached_catalog_payload()
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
            return {"ok": False, "error": f"Command not allowed: {name}"}
