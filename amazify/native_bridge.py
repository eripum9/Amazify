from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .app_updater import ApplicationUpdater, UpdateError
from .devtools import DevToolsClient, DevToolsError
from .lyrics_provider import LyricsProviderError, LyricsProviderService
from .plugin_manager import PluginError, PluginManager

LOG = logging.getLogger(__name__)
BINDING_NAME = "AmazifyNativeCommand"
MAX_NATIVE_REQUEST_BYTES = 16 * 1024
MAX_NATIVE_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PENDING_LYRICS_LOADS = 8
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
        "lyrics.provider.status",
        "lyrics.provider.load",
        "lyrics.provider.cancel",
        "lyrics.provider.clearCache",
    }
)


class NativeBindingBridge:
    def __init__(
        self,
        client: DevToolsClient,
        plugin_manager: PluginManager,
        app_updater: ApplicationUpdater | None = None,
        lyrics_provider: LyricsProviderService | None = None,
        lyrics_state_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.plugin_manager = plugin_manager
        self.app_updater = app_updater
        self.lyrics_provider = lyrics_provider or (
            LyricsProviderService(lyrics_state_dir) if lyrics_state_dir is not None else None
        )
        self._session_nonce = secrets.token_urlsafe(32)
        self._response_callback_name = f"__amazifyNativeResult_{secrets.token_hex(18)}"
        self._operation_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="AmazifyLyrics")
        self._futures: set[Future[dict[str, Any]]] = set()
        self._loads: dict[str, threading.Event] = {}
        self._closed = False

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
        if hasattr(self.client, "on_close"):
            self.client.on_close(self.close)
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
            if name == "lyrics.provider.load":
                self._submit_provider_load(request_id, command_payload)
                return
            with self._operation_lock:
                result = self._handle_command(name, command_payload)
        except (LyricsProviderError, PluginError, UpdateError, TypeError, ValueError) as exc:
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
        if name.startswith("lyrics.provider."):
            if self.lyrics_provider is None:
                raise LyricsProviderError("Lyrics provider is unavailable")
            if name == "lyrics.provider.status":
                return self.lyrics_provider.status()
            if name == "lyrics.provider.cancel":
                key = str(payload.get("requestKey", ""))
                pending = self._loads.get(key)
                if pending is not None:
                    pending.set()
                result = self.lyrics_provider.cancel(key)
                result["canceled"] = bool(pending is not None or result.get("canceled"))
                return result
            if name == "lyrics.provider.clearCache":
                return self.lyrics_provider.clear_cache()
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
        if self._closed:
            return
        serialized = json.dumps(result)
        if len(serialized.encode("utf-8")) > MAX_NATIVE_RESPONSE_BYTES:
            serialized = json.dumps({"ok": False, "error": "Native response was too large"})
        expression = (
            "(() => {"
            f" const callback = window[{json.dumps(self._response_callback_name)}];"
            " if (typeof callback !== 'function') return false;"
            f" return callback({json.dumps(request_id)}, {serialized});"
            "})()"
        )
        try:
            self.client.evaluate_nowait(expression)
        except DevToolsError:
            LOG.debug("Failed to deliver native bridge response", exc_info=True)

    def _submit_provider_load(self, request_id: str, payload: dict[str, Any]) -> None:
        if not request_id:
            raise LyricsProviderError("Lyrics request id is missing")
        if self.lyrics_provider is None:
            raise LyricsProviderError("Lyrics provider is unavailable")
        track = payload.get("track", {})
        if not isinstance(track, dict):
            raise TypeError("Lyrics track payload must be an object")
        request_key = str(payload.get("requestKey", ""))
        if not request_key or len(request_key) > 256:
            raise LyricsProviderError("Lyrics request key is invalid")
        with self._operation_lock:
            if self._closed:
                raise LyricsProviderError("Native bridge is closed")
            if len(self._futures) >= MAX_PENDING_LYRICS_LOADS:
                raise LyricsProviderError("Lyrics request capacity is busy")
            if request_key in self._loads:
                raise LyricsProviderError("Lyrics request key is already pending")
            canceled = threading.Event()
            self._loads[request_key] = canceled
            future = self._executor.submit(self.lyrics_provider.load, track, request_key, cancel_event=canceled)
            self._futures.add(future)

        def complete(done: Future[dict[str, Any]]) -> None:
            with self._operation_lock:
                self._futures.discard(done)
                self._loads.pop(request_key, None)
                if self._closed or canceled.is_set() or done.cancelled():
                    return
            try:
                result = done.result()
            except (LyricsProviderError, TypeError, ValueError) as exc:
                result = {"ok": False, "error": str(exc)}
            except Exception:
                LOG.exception("Asynchronous lyrics provider command failed")
                result = {"ok": False, "error": "Lyrics provider failed"}
            self._reply(request_id, result)

        future.add_done_callback(complete)

    def close(self) -> None:
        with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            futures = list(self._futures)
            for canceled in self._loads.values():
                canceled.set()
        for future in futures:
            future.cancel()
        if self.lyrics_provider is not None:
            self.lyrics_provider.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
