from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from typing import Any

from .app_updater import ApplicationUpdater, UpdateError
from .devtools import DevToolsClient, DevToolsError
from .plugin_manager import PluginError, PluginManager

LOG = logging.getLogger(__name__)
BINDING_NAME = "AmazifyNativeCommand"
MAX_NATIVE_REQUEST_BYTES = 16 * 1024
ALLOWED_COMMANDS = frozenset(
    {
        "state.get",
        "plugins.enable",
        "plugins.disable",
        "catalog.refresh",
        "plugins.install",
        "plugins.disableAll",
        "app.update.status",
        "app.update.check",
        "app.update.install",
    }
)


class NativeBindingBridge:
    def __init__(
        self,
        client: DevToolsClient,
        plugin_manager: PluginManager,
        app_updater: ApplicationUpdater | None = None,
    ) -> None:
        self.client = client
        self.plugin_manager = plugin_manager
        self.app_updater = app_updater
        self._session_nonce = secrets.token_urlsafe(32)
        self._response_callback_name = f"__amazifyNativeResult_{secrets.token_hex(18)}"
        self._operation_lock = threading.RLock()

    @property
    def session_nonce(self) -> str:
        return self._session_nonce

    @property
    def response_callback_name(self) -> str:
        return self._response_callback_name

    def install(self) -> None:
        self.client.call("Runtime.enable")
        try:
            self.client.call("Runtime.addBinding", {"name": BINDING_NAME})
        except DevToolsError as exc:
            if "already" not in str(exc).lower():
                raise
            LOG.debug("DevTools binding already exists: %s", BINDING_NAME)
        self.client.on_event("Runtime.bindingCalled", self.handle_binding_called)
        LOG.info("Installed DevTools native binding: %s", BINDING_NAME)

    def handle_binding_called(self, params: dict[str, Any]) -> None:
        if params.get("name") != BINDING_NAME:
            return
        request_id = ""
        try:
            raw_payload = str(params.get("payload", "{}"))
            if len(raw_payload.encode("utf-8")) > MAX_NATIVE_REQUEST_BYTES:
                raise ValueError("Native binding payload is too large")
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise TypeError("Native binding payload must be an object")
            request_id = str(payload.get("id", ""))
            supplied_nonce = str(payload.get("sessionNonce", ""))
            if not supplied_nonce or not hmac.compare_digest(
                supplied_nonce, self._session_nonce
            ):
                raise PluginError("Native command authentication failed")
            name = str(payload.get("name", ""))
            command_payload = payload.get("payload", {})
            if not isinstance(command_payload, dict):
                raise TypeError("Native command payload must be an object")
            with self._operation_lock:
                result = self._handle_command(name, command_payload)
        except (PluginError, UpdateError, TypeError, ValueError) as exc:
            LOG.warning("Rejected native binding command: %s", exc)
            result = {"ok": False, "error": str(exc)}
        except Exception:
            LOG.exception("Native binding command failed")
            result = {"ok": False, "error": "Native command failed"}
        if request_id:
            self._reply(request_id, result)

    def _handle_command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_COMMANDS:
            raise PluginError(f"Native command not allowed: {name}")
        if name == "state.get":
            return self._state_payload()
        if name == "plugins.enable":
            self.plugin_manager.enable(str(payload.get("pluginId", "")))
            return self._state_payload()
        if name == "plugins.disable":
            self.plugin_manager.disable(str(payload.get("pluginId", "")))
            return self._state_payload()
        if name == "catalog.refresh":
            return self._state_payload(force_catalog_refresh=True)
        if name == "plugins.install":
            self.plugin_manager.install_from_catalog(str(payload.get("pluginId", "")))
            return self._state_payload(force_catalog_refresh=True)
        if name == "plugins.disableAll":
            self.plugin_manager.disable_all()
            return self._state_payload()
        if name == "app.update.status":
            return self._update_payload()
        if name == "app.update.check":
            if self.app_updater is None:
                raise UpdateError("The Amazify application updater is unavailable")
            return {"ok": True, "appUpdate": self.app_updater.start_check()}
        if name == "app.update.install":
            if self.app_updater is None:
                raise UpdateError("The Amazify application updater is unavailable")
            return {"ok": True, "appUpdate": self.app_updater.start_install()}
        raise PluginError(f"Native command not allowed: {name}")

    def _state_payload(self, *, force_catalog_refresh: bool = False) -> dict[str, Any]:
        catalog = (
            self.plugin_manager.catalog_payload(force_refresh=True)
            if force_catalog_refresh
            else self.plugin_manager.cached_catalog_payload()
        )
        payload = {
            "ok": True,
            "plugins": self.plugin_manager.public_plugins(),
            "runtimePlugins": self.plugin_manager.runtime_snapshot(),
            "catalogPlugins": catalog["plugins"],
            "catalogError": catalog["error"],
            "catalogUrl": catalog["url"],
            "bridge": {"type": "devtools-binding"},
        }
        if self.app_updater is not None:
            payload["appUpdate"] = self.app_updater.snapshot()
        return payload

    def _update_payload(self) -> dict[str, Any]:
        if self.app_updater is None:
            raise UpdateError("The Amazify application updater is unavailable")
        return {"ok": True, "appUpdate": self.app_updater.snapshot()}

    def _reply(self, request_id: str, result: dict[str, Any]) -> None:
        expression = (
            "(() => {"
            f" const callback = window[{json.dumps(self._response_callback_name)}];"
            " if (typeof callback !== 'function') return false;"
            f" return callback({json.dumps(request_id)}, {json.dumps(result)});"
            "})()"
        )
        try:
            self.client.evaluate_nowait(expression)
        except DevToolsError:
            LOG.debug("Failed to deliver native bridge response", exc_info=True)
