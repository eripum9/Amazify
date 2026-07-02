from __future__ import annotations

import json
import logging
from typing import Any

from .devtools import DevToolsClient, DevToolsError
from .plugin_manager import PluginError, PluginManager


LOG = logging.getLogger(__name__)
BINDING_NAME = "AmazifyNativeCommand"


class NativeBindingBridge:
    def __init__(self, client: DevToolsClient, plugin_manager: PluginManager) -> None:
        self.client = client
        self.plugin_manager = plugin_manager

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
            payload = json.loads(str(params.get("payload", "{}")))
            if not isinstance(payload, dict):
                raise ValueError("Native binding payload must be an object")
            request_id = str(payload.get("id", ""))
            name = str(payload.get("name", ""))
            command_payload = payload.get("payload", {})
            if not isinstance(command_payload, dict):
                command_payload = {}
            result = self._handle_command(name, command_payload)
        except Exception as exc:
            LOG.exception("Native binding command failed")
            result = {"ok": False, "error": str(exc)}
        if request_id:
            self._reply(request_id, result)

    def _handle_command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        raise PluginError(f"Unknown native command: {name}")

    def _state_payload(self, *, force_catalog_refresh: bool = False) -> dict[str, Any]:
        catalog = self.plugin_manager.catalog_payload(force_refresh=force_catalog_refresh)
        return {
            "ok": True,
            "plugins": self.plugin_manager.public_plugins(),
            "runtimePlugins": self.plugin_manager.runtime_snapshot(),
            "catalogPlugins": catalog["plugins"],
            "catalogError": catalog["error"],
            "catalogUrl": catalog["url"],
            "bridge": {"type": "devtools-binding"},
        }

    def _reply(self, request_id: str, result: dict[str, Any]) -> None:
        expression = (
            "(() => {"
            " if (window.Amazify && typeof window.Amazify.receiveNativeResult === 'function') {"
            f" window.Amazify.receiveNativeResult({json.dumps(request_id)}, {json.dumps(result)});"
            " return true;"
            " }"
            " return false;"
            "})()"
        )
        try:
            self.client.evaluate(expression)
        except DevToolsError:
            LOG.debug("Failed to deliver native bridge response", exc_info=True)
