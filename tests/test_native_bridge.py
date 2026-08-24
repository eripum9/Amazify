from __future__ import annotations

import json
import time
import unittest
from typing import Any, Callable

from amazify.native_bridge import (
    ALLOWED_COMMANDS,
    BINDING_NAME,
    MAX_NATIVE_REQUEST_BYTES,
    NativeBindingBridge,
)


class FakeDevToolsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.expressions: list[str] = []
        self.close_handlers: list[Callable[[], None]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params))
        return {}

    def on_event(self, method: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self.handlers[method] = handler

    def evaluate_nowait(self, expression: str) -> int:
        self.expressions.append(expression)
        return len(self.expressions)

    def on_close(self, handler: Callable[[], None]) -> None:
        self.close_handlers.append(handler)


class StubPluginManager:
    def __init__(self) -> None:
        self.enabled: list[str] = []
        self.disabled: list[str] = []
        self.installed: list[str] = []
        self.disable_all_calls = 0

    def public_plugins(self) -> list[dict[str, Any]]:
        return []

    def runtime_snapshot(self) -> list[dict[str, Any]]:
        return []

    def cached_catalog_payload(self) -> dict[str, Any]:
        return {"plugins": [], "error": "", "url": "catalog"}

    def catalog_payload(self, *, force_refresh: bool) -> dict[str, Any]:
        return {"plugins": [], "error": "", "url": "catalog", "forced": force_refresh}

    def enable(self, plugin_id: str) -> None:
        self.enabled.append(plugin_id)

    def disable(self, plugin_id: str) -> None:
        self.disabled.append(plugin_id)

    def install_from_catalog(self, plugin_id: str) -> None:
        self.installed.append(plugin_id)

    def disable_all(self) -> None:
        self.disable_all_calls += 1


class StubApplicationUpdater:
    def __init__(self) -> None:
        self.check_calls = 0
        self.install_calls = 0
        self.state: dict[str, Any] = {
            "currentVersion": "1.0.0",
            "latestVersion": "1.1.0",
            "status": "available",
            "updateAvailable": True,
        }

    def snapshot(self) -> dict[str, Any]:
        return dict(self.state)

    def start_check(self) -> dict[str, Any]:
        self.check_calls += 1
        self.state["status"] = "checking"
        return self.snapshot()

    def start_install(self) -> dict[str, Any]:
        self.install_calls += 1
        self.state["status"] = "downloading"
        return self.snapshot()


class StubLyricsProvider:
    def __init__(self) -> None:
        self.closed = False
        self.canceled: list[str] = []

    def load(self, track: dict[str, Any], request_key: str) -> dict[str, Any]:
        return {"ok": True, "status": "ready", "trackKey": track.get("key")}

    def cancel(self, request_key: str) -> dict[str, Any]:
        self.canceled.append(request_key)
        return {"ok": True}

    def close(self) -> None:
        self.closed = True

class NativeBindingBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeDevToolsClient()
        self.manager = StubPluginManager()
        self.updater = StubApplicationUpdater()
        self.bridge = NativeBindingBridge(
            self.client,  # type: ignore[arg-type]
            self.manager,  # type: ignore[arg-type]
            self.updater,  # type: ignore[arg-type]
        )

    def send(
        self,
        name: str,
        *,
        nonce: str | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str = "request-1",
    ) -> None:
        request = {
            "id": request_id,
            "name": name,
            "payload": payload or {},
            "sessionNonce": nonce if nonce is not None else self.bridge.session_nonce,
        }
        self.bridge.handle_binding_called(
            {"name": BINDING_NAME, "payload": json.dumps(request)}
        )

    def test_exposes_unique_session_nonce_and_response_callback(self) -> None:
        other = NativeBindingBridge(
            self.client,  # type: ignore[arg-type]
            self.manager,  # type: ignore[arg-type]
        )

        self.assertGreaterEqual(len(self.bridge.session_nonce), 32)
        self.assertNotEqual(self.bridge.session_nonce, other.session_nonce)
        self.assertRegex(
            self.bridge.response_callback_name,
            r"^__amazifyNativeResult_[0-9a-f]{36}$",
        )
        self.assertNotEqual(
            self.bridge.response_callback_name,
            other.response_callback_name,
        )

    def test_install_registers_only_the_explicit_binding(self) -> None:
        self.bridge.install()

        self.assertEqual(
            self.client.calls,
            [
                ("Runtime.enable", None),
                ("Runtime.addBinding", {"name": BINDING_NAME}),
            ],
        )
        registered = self.client.handlers["Runtime.bindingCalled"]
        self.assertIs(registered.__self__, self.bridge)
        self.assertIs(
            registered.__func__,
            self.bridge.handle_binding_called.__func__,
        )

    def test_authenticated_allowlisted_command_executes(self) -> None:
        self.send("plugins.enable", payload={"pluginId": "plugin.example"})

        self.assertEqual(self.manager.enabled, ["plugin.example"])
        self.assertEqual(len(self.client.expressions), 1)
        expression = self.client.expressions[0]
        self.assertIn(self.bridge.response_callback_name, expression)
        self.assertNotIn("CustomEvent", expression)
        self.assertNotIn("window.Amazify", expression)

    def test_missing_or_incorrect_nonce_is_rejected(self) -> None:
        for nonce in ("", "wrong"):
            with self.subTest(nonce=nonce):
                self.send(
                    "plugins.enable",
                    nonce=nonce,
                    payload={"pluginId": "plugin.example"},
                )

        self.assertEqual(self.manager.enabled, [])
        self.assertEqual(len(self.client.expressions), 2)
        self.assertTrue(
            all("authentication failed" in item for item in self.client.expressions)
        )

    def test_non_allowlisted_command_is_rejected(self) -> None:
        self.send("system.shell", payload={"command": "whoami"})

        self.assertEqual(len(self.client.expressions), 1)
        self.assertIn("not allowed", self.client.expressions[0])
        self.assertNotIn("whoami", self.client.expressions[0])

    def test_command_payload_must_be_an_object(self) -> None:
        request = {
            "id": "request-1",
            "name": "state.get",
            "payload": [],
            "sessionNonce": self.bridge.session_nonce,
        }

        self.bridge.handle_binding_called(
            {"name": BINDING_NAME, "payload": json.dumps(request)}
        )

        self.assertIn("must be an object", self.client.expressions[0])

    def test_oversized_native_payload_is_rejected_without_dispatch(self) -> None:
        oversized = "x" * (MAX_NATIVE_REQUEST_BYTES + 1)

        self.bridge.handle_binding_called({"name": BINDING_NAME, "payload": oversized})

        self.assertEqual(self.client.expressions, [])

    def test_allowlist_matches_supported_native_commands(self) -> None:
        self.assertEqual(
            ALLOWED_COMMANDS,
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
                "lyrics.provider.beginAuth",
                "lyrics.provider.disconnect",
                "lyrics.provider.load",
                "lyrics.provider.cancel",
                "lyrics.provider.clearCache",
            },
        )

    def test_application_update_commands_use_dedicated_updater(self) -> None:
        self.send("app.update.check", request_id="check")
        self.send("app.update.status", request_id="status")
        self.send("app.update.install", request_id="install")

        self.assertEqual(self.updater.check_calls, 1)
        self.assertEqual(self.updater.install_calls, 1)
        self.assertEqual(len(self.client.expressions), 3)
        self.assertIn("checking", self.client.expressions[0])
        self.assertIn("downloading", self.client.expressions[2])

    def test_lyrics_load_replies_asynchronously_and_close_revokes_provider(self) -> None:
        provider = StubLyricsProvider()
        bridge = NativeBindingBridge(
            self.client,  # type: ignore[arg-type]
            self.manager,  # type: ignore[arg-type]
            lyrics_provider=provider,  # type: ignore[arg-type]
        )
        request = {
            "id": "lyrics-1",
            "name": "lyrics.provider.load",
            "payload": {"track": {"key": "amazon:key"}, "requestKey": "request"},
            "sessionNonce": bridge.session_nonce,
        }
        bridge.handle_binding_called(
            {"name": BINDING_NAME, "payload": json.dumps(request)}
        )
        deadline = time.monotonic() + 2
        while not self.client.expressions and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("amazon:key", self.client.expressions[0])
        bridge.close()
        self.assertTrue(provider.closed)


if __name__ == "__main__":
    unittest.main()
