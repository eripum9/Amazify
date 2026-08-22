from __future__ import annotations

import json
import unittest
from unittest import mock

from amazify.devtools import (
    MAX_TARGET_LIST_BYTES,
    DevToolsClient,
    DevToolsConnectionClosed,
    DevToolsError,
    DevToolsHttp,
    Target,
    find_amazon_music_target,
    is_amazon_music_target,
    valid_target_websocket,
)
from amazify.launcher import LaunchError


def make_client() -> DevToolsClient:
    return DevToolsClient(
        Target(
            id="target",
            title="Amazon Music",
            url="https://music.amazon.com",
            type="page",
            web_socket_debugger_url="ws://127.0.0.1/devtools/page/target",
        )
    )


def make_target(
    *,
    target_id: str = "target",
    title: str = "Amazon Music",
    url: str = "https://music.amazon.com",
    target_type: str = "page",
    websocket_url: str = "ws://127.0.0.1:61234/devtools/page/target",
    devtools_port: int = 61234,
) -> Target:
    return Target(
        id=target_id,
        title=title,
        url=url,
        type=target_type,
        web_socket_debugger_url=websocket_url,
        devtools_port=devtools_port,
    )


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "http://127.0.0.1:61234/json/list",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.url = url
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


class DevToolsClientTests(unittest.TestCase):
    def test_evaluate_nowait_sends_without_receiving(self) -> None:
        client = make_client()
        client._ws = mock.Mock()

        message_id = client.evaluate_nowait("window.test = true")

        self.assertEqual(message_id, 1)
        client._ws.send.assert_called_once()
        self.assertIn('"method": "Runtime.evaluate"', client._ws.send.call_args.args[0])
        client._ws.recv.assert_not_called()

    def test_empty_websocket_read_is_connection_closed(self) -> None:
        class EmptySocket:
            def recv(self) -> str:
                return ""

        client = make_client()
        client._ws = EmptySocket()

        with self.assertRaises(DevToolsConnectionClosed):
            client._recv_message()

    def test_os_error_websocket_read_is_connection_closed(self) -> None:
        class BrokenSocket:
            def recv(self) -> str:
                raise ConnectionResetError("closed")

        client = make_client()
        client._ws = BrokenSocket()

        with self.assertRaises(DevToolsConnectionClosed):
            client._recv_message()

    def test_connect_rejects_untrusted_websocket_before_network_access(self) -> None:
        client = DevToolsClient(
            make_target(websocket_url="ws://example.com:61234/devtools/page/target")
        )

        with (
            mock.patch.dict("sys.modules", {"websocket": mock.Mock()}),
            self.assertRaisesRegex(DevToolsError, "trusted loopback target"),
        ):
            client.connect()

    def test_connect_suppresses_origin_bypasses_proxy_and_revalidates(self) -> None:
        websocket = mock.Mock()
        client = DevToolsClient(make_target())

        with (
            mock.patch.dict("sys.modules", {"websocket": websocket}),
            mock.patch("amazify.devtools.validate_devtools_listener") as validate,
        ):
            client.connect()

        websocket.create_connection.assert_called_once_with(
            "ws://127.0.0.1:61234/devtools/page/target",
            timeout=5.0,
            enable_multithread=True,
            suppress_origin=True,
            http_no_proxy=["127.0.0.1", "::1", "localhost"],
        )
        self.assertEqual(validate.call_args_list, [mock.call(61234), mock.call(61234)])

    def test_connect_closes_socket_when_post_connect_validation_fails(self) -> None:
        socket = mock.Mock()
        websocket = mock.Mock()
        websocket.create_connection.return_value = socket
        client = DevToolsClient(make_target())

        with (
            mock.patch.dict("sys.modules", {"websocket": websocket}),
            mock.patch(
                "amazify.devtools.validate_devtools_listener",
                side_effect=[None, LaunchError("listener changed")],
            ),
            self.assertRaisesRegex(DevToolsError, "listener changed"),
        ):
            client.connect()

        socket.close.assert_called_once_with()
        self.assertIsNone(client._ws)


class DevToolsTargetSecurityTests(unittest.TestCase):
    def test_accepts_exact_amazon_music_target_and_matching_websocket(self) -> None:
        target = make_target()

        self.assertTrue(is_amazon_music_target(target))
        self.assertTrue(valid_target_websocket(target, 61234))
        self.assertIs(
            find_amazon_music_target([target], expected_port=61234),
            target,
        )

    def test_accepts_regional_morpho_webapp_target(self) -> None:
        target = make_target(
            title="Amazon Music Web App",
            url="https://www.amazon.de/morpho/webapp/player",
        )

        self.assertTrue(is_amazon_music_target(target))

    def test_rejects_lookalike_or_insecure_amazon_urls(self) -> None:
        targets = [
            make_target(url="https://music.amazon.com.example.org"),
            make_target(url="http://music.amazon.com"),
            make_target(url="https://user@music.amazon.com"),
            make_target(url="https://www.amazon.com/not-the-webapp"),
            make_target(title="Not Amazon Music"),
        ]

        self.assertTrue(all(not is_amazon_music_target(target) for target in targets))

    def test_rejects_websocket_with_wrong_endpoint_components(self) -> None:
        targets = [
            make_target(websocket_url="wss://127.0.0.1:61234/devtools/page/target"),
            make_target(websocket_url="ws://example.com:61234/devtools/page/target"),
            make_target(websocket_url="ws://127.0.0.1:61235/devtools/page/target"),
            make_target(websocket_url="ws://127.0.0.1:61234/devtools/page/other"),
            make_target(websocket_url="ws://127.0.0.1:61234/devtools/page/target?q=1"),
        ]

        self.assertTrue(
            all(not valid_target_websocket(target, 61234) for target in targets)
        )

    def test_http_client_rejects_non_loopback_host(self) -> None:
        with self.assertRaisesRegex(DevToolsError, "must be loopback"):
            DevToolsHttp(61234, host="example.com")

    def test_target_list_is_bounded(self) -> None:
        response = FakeResponse(b"[" + b" " * MAX_TARGET_LIST_BYTES + b"]")

        with mock.patch("amazify.devtools._open_devtools_url", return_value=response):
            with self.assertRaisesRegex(DevToolsError, "exceeded 1 MiB"):
                DevToolsHttp(61234).list_targets()

    def test_target_list_rejects_redirect(self) -> None:
        response = FakeResponse(b"[]", url="https://example.com/json/list")

        with mock.patch("amazify.devtools._open_devtools_url", return_value=response):
            with self.assertRaisesRegex(DevToolsError, "redirected unexpectedly"):
                DevToolsHttp(61234).list_targets()

    def test_target_list_records_selected_port(self) -> None:
        payload = [
            {
                "id": "target",
                "title": "Amazon Music",
                "url": "https://music.amazon.com",
                "type": "page",
                "webSocketDebuggerUrl": ("ws://127.0.0.1:61234/devtools/page/target"),
            }
        ]
        response = FakeResponse(json.dumps(payload).encode("utf-8"))

        with mock.patch("amazify.devtools._open_devtools_url", return_value=response):
            targets = DevToolsHttp(61234).list_targets()

        self.assertEqual(targets[0].devtools_port, 61234)

    def test_wait_validates_listener_owner_before_returning_target(self) -> None:
        target = make_target()
        http = DevToolsHttp(61234)

        with (
            mock.patch.object(http, "list_targets", return_value=[target]),
            mock.patch("amazify.devtools.validate_devtools_listener") as validate,
        ):
            selected = http.wait_for_amazon_music_target(timeout_seconds=0.1)

        self.assertIs(selected, target)
        validate.assert_called_once_with(61234)

    def test_wait_fails_closed_when_listener_owner_is_untrusted(self) -> None:
        target = make_target()
        http = DevToolsHttp(61234)

        with (
            mock.patch.object(http, "list_targets", return_value=[target]),
            mock.patch(
                "amazify.devtools.validate_devtools_listener",
                side_effect=__import__(
                    "amazify.launcher", fromlist=["LaunchError"]
                ).LaunchError("listener rejected"),
            ),
            self.assertRaisesRegex(DevToolsError, "listener rejected"),
        ):
            http.wait_for_amazon_music_target(timeout_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
