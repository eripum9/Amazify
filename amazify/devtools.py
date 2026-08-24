from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .config import DEVTOOLS_HOST
from .launcher import LaunchError, validate_devtools_listener

LOG = logging.getLogger(__name__)
AMAZON_REGION_SUFFIXES = (
    "com",
    "de",
    "co.uk",
    "fr",
    "it",
    "es",
    "co.jp",
    "ca",
    "com.au",
    "com.br",
    "com.mx",
)
AMAZON_MUSIC_HOSTS = frozenset(
    f"music.amazon.{suffix}" for suffix in AMAZON_REGION_SUFFIXES
)
AMAZON_WEBAPP_HOSTS = frozenset(
    host
    for suffix in AMAZON_REGION_SUFFIXES
    for host in (f"music.amazon.{suffix}", f"www.amazon.{suffix}")
)
LOOPBACK_DEVTOOLS_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
WEBSOCKET_NO_PROXY_HOSTS = ("127.0.0.1", "::1", "localhost")
MAX_TARGET_LIST_BYTES = 1024 * 1024
DEVTOOLS_PAGE_PATH_RE = re.compile(r"^/devtools/page/([A-Za-z0-9._:-]+)$")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _open_devtools_url(url: str, timeout: float) -> Any:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )
    return opener.open(url, timeout=timeout)


class DevToolsError(RuntimeError):
    pass


class DevToolsConnectionClosed(DevToolsError):
    pass


@dataclass(slots=True)
class Target:
    id: str
    title: str
    url: str
    type: str
    web_socket_debugger_url: str
    devtools_port: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any], *, devtools_port: int = 0) -> "Target":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            type=str(data.get("type", "")),
            web_socket_debugger_url=str(data.get("webSocketDebuggerUrl", "")),
            devtools_port=devtools_port,
        )


class DevToolsHttp:
    def __init__(
        self,
        port: int,
        host: str = DEVTOOLS_HOST,
        request_timeout: float = 1.0,
    ) -> None:
        try:
            selected_port = int(port)
        except (TypeError, ValueError) as exc:
            raise DevToolsError("DevTools port is invalid") from exc
        if not 0 < selected_port <= 65535:
            raise DevToolsError("DevTools port is invalid")
        selected_host = str(host or "").lower()
        if selected_host not in LOOPBACK_DEVTOOLS_HOSTS:
            raise DevToolsError("DevTools HTTP host must be loopback")
        self.port = selected_port
        self.host = selected_host
        self.request_timeout = request_timeout

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if self.host == "::1" else self.host
        return f"http://{host}:{self.port}"

    def list_targets(self) -> list[Target]:
        url = f"{self.base_url}/json/list"
        try:
            with _open_devtools_url(url, self.request_timeout) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else url
                if final_url != url:
                    raise DevToolsError("DevTools target list redirected unexpectedly")
                advertised_length = response.headers.get("Content-Length")
                if advertised_length is not None:
                    try:
                        if int(advertised_length) > MAX_TARGET_LIST_BYTES:
                            raise DevToolsError("DevTools target list exceeded 1 MiB")
                    except ValueError as exc:
                        raise DevToolsError(
                            "DevTools target list returned an invalid Content-Length"
                        ) from exc
                raw = response.read(MAX_TARGET_LIST_BYTES + 1)
                if len(raw) > MAX_TARGET_LIST_BYTES:
                    raise DevToolsError("DevTools target list exceeded 1 MiB")
                data = json.loads(raw.decode("utf-8"))
        except DevToolsError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as exc:
            raise DevToolsError(
                f"Unable to read DevTools target list at {url}"
            ) from exc
        if not isinstance(data, list):
            raise DevToolsError("DevTools target list returned unexpected data")
        return [
            Target.from_json(item, devtools_port=self.port)
            for item in data
            if isinstance(item, dict)
        ]

    def wait_for_amazon_music_target(self, timeout_seconds: float = 25.0) -> Target:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                target = find_amazon_music_target(
                    self.list_targets(), expected_port=self.port
                )
            except DevToolsError as exc:
                last_error = exc
                time.sleep(0.5)
                continue
            if target:
                try:
                    validate_devtools_listener(self.port)
                except LaunchError as exc:
                    raise DevToolsError(str(exc)) from exc
                return target
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
        self._send_lock = threading.RLock()
        self._close_callbacks: list[Callable[[], None]] = []
        self._closed = False

    def connect(self) -> None:
        expected_port = self.target.devtools_port or _websocket_port(
            self.target.web_socket_debugger_url
        )
        if not valid_target_websocket(self.target, expected_port):
            raise DevToolsError(
                "DevTools WebSocket endpoint did not match the trusted loopback target"
            )
        try:
            validate_devtools_listener(expected_port)
        except LaunchError as exc:
            raise DevToolsError(str(exc)) from exc
        try:
            import websocket
        except ImportError as exc:
            raise DevToolsError(
                "Missing dependency websocket-client. Install with: python -m pip install -r requirements.txt"
            ) from exc
        socket = websocket.create_connection(
            self.target.web_socket_debugger_url,
            timeout=self.timeout,
            enable_multithread=True,
            suppress_origin=True,
            http_no_proxy=list(WEBSOCKET_NO_PROXY_HOSTS),
        )
        try:
            validate_devtools_listener(expected_port)
        except Exception as exc:
            try:
                socket.close()
            except Exception:
                LOG.debug(
                    "Unable to close rejected DevTools WebSocket",
                    exc_info=True,
                )
            if isinstance(exc, LaunchError):
                raise DevToolsError(str(exc)) from exc
            raise
        self._ws = socket
        self._closed = False

    def close(self) -> None:
        callbacks: list[Callable[[], None]] = []
        with self._send_lock:
            if not self._closed:
                self._closed = True
                callbacks = list(self._close_callbacks)
                self._close_callbacks.clear()
            socket = self._ws
            self._ws = None
        for callback in callbacks:
            try:
                callback()
            except Exception:
                LOG.debug("DevTools close callback failed", exc_info=True)
        if socket is not None:
            socket.close()

    def on_close(self, callback: Callable[[], None]) -> None:
        with self._send_lock:
            if self._closed:
                callback()
                return
            self._close_callbacks.append(callback)

    def _send(self, method: str, params: dict[str, Any]) -> int:
        with self._send_lock:
            if self._ws is None:
                raise DevToolsError("DevTools WebSocket is not connected")
            self._message_id += 1
            message_id = self._message_id
            self._ws.send(
                json.dumps({"id": message_id, "method": method, "params": params})
            )
            return message_id

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._send(method, params or {})
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
        message_id = self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
                "userGesture": True,
            },
        )
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
                text = details.get("exception", {}).get("description") or details.get(
                    "text"
                )
                raise DevToolsError(f"Runtime.evaluate failed: {text}")
            remote = result.get("result", {})
            if "value" in remote:
                return remote["value"]
            return remote

    def evaluate_nowait(
        self,
        expression: str,
        *,
        await_promise: bool = True,
        return_by_value: bool = True,
    ) -> int:
        """Send an evaluation without recursively reading from the DevTools socket."""
        return self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
                "userGesture": True,
            },
        )

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
        try:
            import websocket
        except ImportError:
            websocket = None
        try:
            raw = self._ws.recv()
        except Exception as exc:
            if websocket is not None and isinstance(
                exc, websocket.WebSocketTimeoutException
            ):
                raise
            if websocket is not None and isinstance(
                exc, websocket.WebSocketConnectionClosedException
            ):
                raise DevToolsConnectionClosed(
                    "DevTools WebSocket connection closed"
                ) from exc
            if isinstance(exc, (ConnectionResetError, BrokenPipeError, OSError)):
                raise DevToolsConnectionClosed(
                    "DevTools WebSocket connection closed"
                ) from exc
            raise
        if raw in ("", None):
            raise DevToolsConnectionClosed("DevTools WebSocket connection closed")
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


def find_amazon_music_target(
    targets: list[Target], *, expected_port: int
) -> Target | None:
    ranked: list[tuple[int, Target]] = []
    for target in targets:
        if not is_amazon_music_target(target):
            continue
        if not valid_target_websocket(target, expected_port):
            continue
        host = (urllib.parse.urlparse(target.url).hostname or "").lower()
        ranked.append((2 if host in AMAZON_MUSIC_HOSTS else 1, target))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked else None


def is_amazon_music_target(target: Target) -> bool:
    if target.type != "page":
        return False
    parsed = urllib.parse.urlparse(target.url)
    try:
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in AMAZON_WEBAPP_HOSTS
        or port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        return False
    title = target.title.strip().lower()
    path = (parsed.path or "").lower()
    if host in AMAZON_MUSIC_HOSTS:
        return title == "amazon music"
    return "morpho/webapp" in path and title.startswith("amazon music")


def valid_target_websocket(target: Target, expected_port: int) -> bool:
    try:
        selected_port = int(expected_port)
    except (TypeError, ValueError):
        return False
    if not 0 < selected_port <= 65535:
        return False
    parsed = urllib.parse.urlparse(target.web_socket_debugger_url)
    try:
        websocket_port = parsed.port
    except ValueError:
        return False
    match = DEVTOOLS_PAGE_PATH_RE.fullmatch(parsed.path or "")
    return bool(
        parsed.scheme.lower() == "ws"
        and (parsed.hostname or "").lower() in LOOPBACK_DEVTOOLS_HOSTS
        and websocket_port == selected_port
        and not parsed.username
        and not parsed.password
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and match
        and match.group(1) == target.id
    )


def exact_https_origin(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or host not in AMAZON_WEBAPP_HOSTS
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return ""
    return f"https://{host}"


def _websocket_port(value: str) -> int:
    try:
        parsed = urllib.parse.urlparse(value)
        return int(parsed.port or 0)
    except (TypeError, ValueError):
        return 0
