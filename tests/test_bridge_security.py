from __future__ import annotations

import concurrent.futures
import hmac
import http.client
import json
import threading
import time
import unittest
from typing import Any
from unittest import mock

from amazify.bridge import MAX_REQUEST_BYTES, LocalBridge


class StubPluginManager:
    def __init__(self) -> None:
        self.enabled: list[str] = []
        self.disabled: list[str] = []
        self.installed: list[str] = []
        self.disable_all_calls = 0
        self.delay_public_plugins = False
        self.active_calls = 0
        self.max_active_calls = 0
        self._counter_lock = threading.Lock()

    def public_plugins(self) -> list[dict[str, Any]]:
        with self._counter_lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.delay_public_plugins:
                time.sleep(0.03)
            return []
        finally:
            with self._counter_lock:
                self.active_calls -= 1

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


class BridgeSecurityTests(unittest.TestCase):
    token = "test-token-with-enough-entropy"
    origin = "https://music.amazon.com"

    def setUp(self) -> None:
        self.manager = StubPluginManager()
        self.bridge = LocalBridge(
            port=0,
            token=self.token,
            plugin_manager=self.manager,  # type: ignore[arg-type]
        )
        self.bridge.start()

    def tearDown(self) -> None:
        self.bridge.stop()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        request_headers = dict(headers or {})
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.bridge.port, timeout=3
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            response_body = response.read()
            return response.status, dict(response.getheaders()), response_body
        finally:
            connection.close()

    def protected_headers(self, **overrides: str) -> dict[str, str]:
        headers = {
            "Host": f"127.0.0.1:{self.bridge.port}",
            "Origin": self.origin,
            "X-Amazify-Token": self.token,
        }
        headers.update(overrides)
        return headers

    def test_approved_origin_can_read_state(self) -> None:
        status, headers, body = self.request(
            "GET", "/state", headers=self.protected_headers()
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], self.origin)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(json.loads(body)["ok"])

    def test_protected_endpoint_rejects_missing_or_unapproved_origin(self) -> None:
        missing_origin = self.protected_headers()
        missing_origin.pop("Origin")
        status, headers, _ = self.request("GET", "/state", headers=missing_origin)
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")

        status, headers, _ = self.request(
            "GET",
            "/state",
            headers=self.protected_headers(Origin="https://example.com"),
        )
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_rejects_non_loopback_or_wrong_port_host(self) -> None:
        for host in ("example.com", "127.0.0.1:1"):
            status, _, _ = self.request(
                "GET", "/state", headers=self.protected_headers(Host=host)
            )
            self.assertEqual(status, 403)

    def test_token_authentication_uses_compare_digest(self) -> None:
        with mock.patch(
            "amazify.bridge.hmac.compare_digest", wraps=hmac.compare_digest
        ) as compare_digest:
            status, _, _ = self.request(
                "GET",
                "/state",
                headers=self.protected_headers(**{"X-Amazify-Token": "wrong"}),
            )

        self.assertEqual(status, 401)
        compare_digest.assert_called_once_with("wrong", self.token)

    def test_health_allows_local_diagnostics_without_origin_or_token(self) -> None:
        status, headers, body = self.request(
            "GET",
            "/health",
            headers={"Host": f"localhost:{self.bridge.port}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["app"], "Amazify")

    def test_preflight_echoes_only_approved_origin(self) -> None:
        headers = {
            "Host": f"127.0.0.1:{self.bridge.port}",
            "Origin": self.origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-amazify-token",
        }

        status, response_headers, body = self.request(
            "OPTIONS", "/plugins/enable", headers=headers
        )

        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        self.assertEqual(response_headers["Access-Control-Allow-Origin"], self.origin)
        self.assertEqual(response_headers["Cache-Control"], "no-store")

    def test_preflight_rejects_unapproved_method_or_header(self) -> None:
        base_headers = {
            "Host": f"127.0.0.1:{self.bridge.port}",
            "Origin": self.origin,
            "Access-Control-Request-Method": "DELETE",
        }
        status, _, _ = self.request("OPTIONS", "/state", headers=base_headers)
        self.assertEqual(status, 403)

        base_headers["Access-Control-Request-Method"] = "POST"
        base_headers["Access-Control-Request-Headers"] = "x-untrusted"
        status, _, _ = self.request("OPTIONS", "/state", headers=base_headers)
        self.assertEqual(status, 403)

    def test_post_rejects_oversized_body_without_reading_it(self) -> None:
        headers = self.protected_headers(
            **{
                "Content-Type": "application/json",
                "Content-Length": str(MAX_REQUEST_BYTES + 1),
            }
        )

        status, _, body = self.request(
            "POST", "/plugins/enable", body=b"", headers=headers
        )

        self.assertEqual(status, 413)
        self.assertIn("too large", json.loads(body)["error"])

    def test_post_requires_strict_json_object(self) -> None:
        cases = [
            (b"not-json", "application/json"),
            (b"[]", "application/json"),
            (b"{}", "text/plain"),
        ]
        for body, content_type in cases:
            with self.subTest(body=body, content_type=content_type):
                headers = self.protected_headers(
                    **{
                        "Content-Type": content_type,
                        "Content-Length": str(len(body)),
                    }
                )
                status, _, _ = self.request(
                    "POST", "/plugins/enable", body=body, headers=headers
                )
                self.assertEqual(status, 400)

    def test_plugin_manager_operations_are_synchronized(self) -> None:
        self.manager.delay_public_plugins = True

        def read_state(_: int) -> int:
            status, _, _ = self.request(
                "GET", "/state", headers=self.protected_headers()
            )
            return status

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(read_state, range(6)))

        self.assertEqual(statuses, [200] * 6)
        self.assertEqual(self.manager.max_active_calls, 1)

    def test_command_endpoint_rejects_non_allowlisted_names(self) -> None:
        body = json.dumps(
            {"name": "system.shell", "payload": {"command": "whoami"}}
        ).encode()
        headers = self.protected_headers(
            **{
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        )

        status, _, response = self.request(
            "POST",
            "/command",
            body=body,
            headers=headers,
        )

        self.assertEqual(status, 200)
        result = json.loads(response)
        self.assertFalse(result["ok"])
        self.assertIn("not allowed", result["error"])
        self.assertNotIn("whoami", response.decode())


if __name__ == "__main__":
    unittest.main()
