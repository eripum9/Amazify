from __future__ import annotations

import unittest

from amazify.devtools import DevToolsClient, DevToolsConnectionClosed, Target


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


class DevToolsClientTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
