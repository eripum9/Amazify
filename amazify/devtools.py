from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .config import DEVTOOLS_HOST


LOG = logging.getLogger(__name__)


class DevToolsError(RuntimeError):
    pass


@dataclass(slots=True)
class Target:
    id: str
    title: str
    url: str
    type: str
    web_socket_debugger_url: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Target":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            type=str(data.get("type", "")),
            web_socket_debugger_url=str(data.get("webSocketDebuggerUrl", "")),
        )


class DevToolsHttp:
    def __init__(self, port: int, host: str = DEVTOOLS_HOST) -> None:
        self.port = port
        self.host = host

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def list_targets(self) -> list[Target]:
        url = f"{self.base_url}/json/list"
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise DevToolsError(f"Unable to read DevTools target list at {url}") from exc
        if not isinstance(data, list):
            raise DevToolsError("DevTools target list returned unexpected data")
        return [Target.from_json(item) for item in data if isinstance(item, dict)]

    def wait_for_amazon_music_target(self, timeout_seconds: float = 25.0) -> Target:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                target = find_amazon_music_target(self.list_targets())
                if target:
                    return target
            except DevToolsError as exc:
                last_error = exc
            time.sleep(0.5)
        detail = f": {last_error}" if last_error else ""
        raise DevToolsError(f"No Amazon Music DevTools target found{detail}")


class DevToolsClient:
    def __init__(self, target: Target, timeout: float = 5.0) -> None:
        self.target = target
        self.timeout = timeout
        self._message_id = 0
        self._ws: Any | None = None
        self._event_handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise DevToolsError(
                "Missing dependency websocket-client. Install with: python -m pip install -r requirements.txt"
            ) from exc
        self._ws = websocket.create_connection(
            self.target.web_socket_debugger_url,
            timeout=self.timeout,
            enable_multithread=True,
        )

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise DevToolsError("DevTools WebSocket is not connected")
        self._message_id += 1
        message_id = self._message_id
        payload = {
            "id": message_id,
            "method": method,
            "params": params or {},
        }
        self._ws.send(json.dumps(payload))
        while True:
            data = self._recv_message()
            if data.get("id") != message_id:
                self._dispatch_event(data)
                continue
            if "error" in data:
                raise DevToolsError(str(data["error"]))
            return data.get("result", {})

    def evaluate(
        self,
        expression: str,
        *,
        await_promise: bool = True,
        return_by_value: bool = True,
    ) -> Any:
        if self._ws is None:
            raise DevToolsError("DevTools WebSocket is not connected")
        self._message_id += 1
        message_id = self._message_id
        payload = {
            "id": message_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
                "userGesture": True,
            },
        }
        self._ws.send(json.dumps(payload))
        while True:
            data = self._recv_message()
            if data.get("id") != message_id:
                self._dispatch_event(data)
                continue
            if "error" in data:
                raise DevToolsError(str(data["error"]))
            result = data.get("result", {})
            if "exceptionDetails" in result:
                details = result["exceptionDetails"]
                text = details.get("exception", {}).get("description") or details.get("text")
                raise DevToolsError(f"Runtime.evaluate failed: {text}")
            remote = result.get("result", {})
            if "value" in remote:
                return remote["value"]
            return remote

    def on_event(self, method: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self._event_handlers[method] = handler

    def pump(self, timeout: float = 0.5) -> bool:
        if self._ws is None:
            raise DevToolsError("DevTools WebSocket is not connected")
        try:
            import websocket
        except ImportError as exc:
            raise DevToolsError("Missing dependency websocket-client") from exc

        previous_timeout = self._ws.gettimeout()
        self._ws.settimeout(timeout)
        try:
            data = self._recv_message()
        except websocket.WebSocketTimeoutException:
            return False
        finally:
            self._ws.settimeout(previous_timeout)
        self._dispatch_event(data)
        return True

    def _recv_message(self) -> dict[str, Any]:
        if self._ws is None:
            raise DevToolsError("DevTools WebSocket is not connected")
        raw = self._ws.recv()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise DevToolsError("Unexpected DevTools WebSocket message")
        return data

    def _dispatch_event(self, data: dict[str, Any]) -> None:
        method = data.get("method")
        if not isinstance(method, str):
            return
        handler = self._event_handlers.get(method)
        if handler:
            handler(data.get("params", {}))

    def probe_amazon_music(self) -> dict[str, Any]:
        probe = """
(() => {
  const title = document.title || "";
  const href = location.href || "";
  const bodyText = ((document.body && document.body.innerText) || "").slice(0, 4000);
  const hasSearch = Array.from(document.querySelectorAll("input")).some((input) => {
    const placeholder = String(input.getAttribute("placeholder") || "").toLowerCase();
    const type = String(input.getAttribute("type") || "").toLowerCase();
    return type === "search" || placeholder.includes("search") || placeholder.includes("suche");
  });
  const hasMedia = !!document.querySelector('audio, video');
  const amazonSignals = [
    title,
    href,
    (document.querySelector('meta[property="og:site_name"]') && document.querySelector('meta[property="og:site_name"]').content) || "",
    bodyText
  ].join("\\n").toLowerCase();
  return {
    title,
    href,
    hasSearch,
    hasMedia,
    looksAmazonMusic:
      amazonSignals.includes("amazon music") ||
      amazonSignals.includes("music.amazon") ||
      amazonSignals.includes("amazonmusic")
  };
})()
""".strip()
        value = self.evaluate(probe)
        if not isinstance(value, dict):
            raise DevToolsError("Amazon Music probe returned unexpected data")
        if not bool(value.get("looksAmazonMusic")):
            raise DevToolsError(
                f"DevTools target did not pass Amazon Music probe: {value!r}"
            )
        return value


def find_amazon_music_target(targets: list[Target]) -> Target | None:
    ranked: list[tuple[int, Target]] = []
    for target in targets:
        if target.type and target.type != "page":
            continue
        if not target.web_socket_debugger_url:
            continue
        title = target.title.lower()
        url = target.url.lower()
        if _is_obviously_unrelated(url):
            continue
        score = 0
        if "amazon music" in title:
            score += 10
        if "music.amazon" in url:
            score += 10
        if "amazonmusic" in url or "amazon-music" in url:
            score += 6
        if "amazon" in title and "music" in title:
            score += 5
        if score:
            ranked.append((score, target))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked else None


def _is_obviously_unrelated(url: str) -> bool:
    if not url:
        return False
    blocked_prefixes = (
        "devtools://",
        "chrome://",
        "edge://",
        "about:",
    )
    if url.startswith(blocked_prefixes):
        return True
    unrelated_hosts = (
        "localhost",
        "127.0.0.1",
        "github.com",
        "google.com",
        "bing.com",
    )
    return any(host in url for host in unrelated_hosts)
