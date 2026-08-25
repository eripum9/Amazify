from __future__ import annotations

import base64
import ctypes
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable


AUTHORIZATION_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
CALLBACK_TIMEOUT_SECONDS = 300


class SpotifyAuthError(RuntimeError):
    pass


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


def _strict_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class DpapiTokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, token: str) -> None:
        if os.name != "nt":
            raise SpotifyAuthError("Spotify credential storage requires Windows DPAPI")
        raw = token.encode("utf-8")
        encrypted = self._protect(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)

    def load(self) -> str:
        if not self.path.exists():
            return ""
        if os.name != "nt":
            return ""
        try:
            return self._unprotect(self.path.read_bytes()).decode("utf-8")
        except (OSError, UnicodeDecodeError, SpotifyAuthError):
            return ""

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _protect(data: bytes) -> bytes:
        input_buffer = ctypes.create_string_buffer(data)
        input_blob = _DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte)))
        output_blob = _DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
        ):
            raise SpotifyAuthError("Unable to protect Spotify refresh token")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _unprotect(data: bytes) -> bytes:
        input_buffer = ctypes.create_string_buffer(data)
        input_blob = _DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte)))
        output_blob = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)
        ):
            raise SpotifyAuthError("Unable to read Spotify refresh token")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)


class _CallbackServer(http.server.ThreadingHTTPServer):
    oauth_result: dict[str, str] | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server_version = "AmazifyOAuth/1"

    def do_GET(self) -> None:
        server = self.server
        if not isinstance(server, _CallbackServer):
            self.send_error(500)
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        server.oauth_result = {
            "code": str(query.get("code", [""])[0]),
            "state": str(query.get("state", [""])[0]),
            "error": str(query.get("error", [""])[0]),
        }
        body = b"Amazify connected to Spotify. You can close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class SpotifyAuth:
    def __init__(
        self,
        state_dir: Path,
        *,
        client_id: str | None = None,
        opener: urllib.request.OpenerDirector | None = None,
        browser_open: Callable[[str], Any] = webbrowser.open,
        now: Callable[[], float] = time.time,
        token_store: DpapiTokenStore | None = None,
    ) -> None:
        self.client_id = str(client_id or os.environ.get("AMAZIFY_SPOTIFY_CLIENT_ID", "")).strip()
        self._opener = opener or _strict_opener()
        self._browser_open = browser_open
        self._now = now
        self._store = token_store or DpapiTokenStore(state_dir / "spotify_refresh_token.bin")
        self._lock = threading.RLock()
        self._access_token = ""
        self._expires_at = 0.0
        self._refresh_token = self._store.load()
        self._status = "connected" if self._refresh_token else "disconnected"
        self._detail = ""
        self._auth_thread: threading.Thread | None = None
        self._callback_server: _CallbackServer | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": bool(self.client_id),
                "state": self._status if self.client_id else "unconfigured",
                "connected": bool(self._refresh_token or self._access_token),
                "detail": self._detail,
            }

    def begin_auth(self) -> dict[str, Any]:
        if not self.client_id:
            raise SpotifyAuthError("Spotify provider is not configured in this build")
        with self._lock:
            if self._auth_thread and self._auth_thread.is_alive():
                return self.status()
            self._status = "connecting"
            self._detail = "Complete authorization in your browser."
            self._auth_thread = threading.Thread(
                target=self._authorization_worker,
                name="AmazifySpotifyAuth",
                daemon=True,
            )
            self._auth_thread.start()
        return self.status()

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._access_token = ""
            self._expires_at = 0.0
            self._refresh_token = ""
            self._status = "disconnected"
            self._detail = ""
            self._store.clear()
        return self.status()

    def access_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            if not force_refresh and self._access_token and self._expires_at > self._now() + 30:
                return self._access_token
            refresh_token = self._refresh_token
        if not refresh_token:
            raise SpotifyAuthError("Spotify is not connected")
        payload = self._request_token({
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        return self._accept_token_payload(payload, previous_refresh=refresh_token)

    def invalidate_access_token(self) -> None:
        with self._lock:
            self._access_token = ""
            self._expires_at = 0.0

    def close(self) -> None:
        with self._lock:
            server = self._callback_server
            self._callback_server = None
        if server is not None:
            server.server_close()

    def _authorization_worker(self) -> None:
        verifier = secrets.token_urlsafe(72)
        state = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        server: _CallbackServer | None = None
        try:
            server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
            server.timeout = 0.5
            with self._lock:
                self._callback_server = server
            port = int(server.server_address[1])
            redirect_uri = f"http://127.0.0.1:{port}/callback"
            query = urllib.parse.urlencode({
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
                "scope": "",
            })
            if not self._browser_open(f"{AUTHORIZATION_URL}?{query}"):
                raise SpotifyAuthError("Unable to open the Spotify authorization page")
            deadline = time.monotonic() + CALLBACK_TIMEOUT_SECONDS
            while time.monotonic() < deadline and server.oauth_result is None:
                server.handle_request()
            result = server.oauth_result
            if not isinstance(result, dict):
                raise SpotifyAuthError("Spotify authorization timed out")
            if not secrets.compare_digest(str(result.get("state", "")), state):
                raise SpotifyAuthError("Spotify authorization state did not match")
            if result.get("error"):
                raise SpotifyAuthError("Spotify authorization was declined")
            code = str(result.get("code", ""))
            if not code:
                raise SpotifyAuthError("Spotify authorization returned no code")
            payload = self._request_token({
                "client_id": self.client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            })
            self._accept_token_payload(payload)
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._detail = str(exc) if isinstance(exc, SpotifyAuthError) else "Spotify authorization failed"
        finally:
            if server is not None:
                server.server_close()
            with self._lock:
                if self._callback_server is server:
                    self._callback_server = None

    def _request_token(self, form: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(form).encode("ascii")
        request = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                if response.geturl() != TOKEN_URL:
                    raise SpotifyAuthError("Spotify token endpoint redirected unexpectedly")
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "application/json" not in content_type:
                    raise SpotifyAuthError("Spotify token endpoint returned an invalid content type")
                raw = response.read(MAX_TOKEN_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise SpotifyAuthError(f"Spotify token request failed ({exc.code})") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise SpotifyAuthError("Spotify token request failed") from exc
        if len(raw) > MAX_TOKEN_RESPONSE_BYTES:
            raise SpotifyAuthError("Spotify token response was too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpotifyAuthError("Spotify token response was invalid") from exc
        if not isinstance(payload, dict):
            raise SpotifyAuthError("Spotify token response was invalid")
        return payload

    def _accept_token_payload(
        self, payload: dict[str, Any], *, previous_refresh: str = ""
    ) -> str:
        access_token = str(payload.get("access_token", ""))
        refresh_token = str(payload.get("refresh_token", "")) or previous_refresh
        try:
            expires_in = max(60, min(86400, int(payload.get("expires_in", 3600))))
        except (TypeError, ValueError):
            expires_in = 3600
        if not access_token or not refresh_token:
            raise SpotifyAuthError("Spotify token response was incomplete")
        self._store.save(refresh_token)
        with self._lock:
            self._access_token = access_token
            self._refresh_token = refresh_token
            self._expires_at = self._now() + expires_in
            self._status = "connected"
            self._detail = ""
        return access_token
