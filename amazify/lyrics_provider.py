from __future__ import annotations

import json
import random
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .lyrics_cache import LyricsCache
from .spotify_auth import SpotifyAuth, SpotifyAuthError


SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
SPICY_QUERY_URL = "https://api.spicylyrics.org/query"
SPICY_VERSION = "1.1"
RESOLVER_VERSION = 1
MAX_NETWORK_BYTES = 2 * 1024 * 1024
QUALIFIERS = frozenset(
    {"live", "remix", "acoustic", "instrumental", "karaoke", "remaster", "sped up", "slowed"}
)


class LyricsProviderError(RuntimeError):
    pass


class LyricsUnavailable(LyricsProviderError):
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


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _qualifiers(value: Any) -> set[str]:
    folded = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return {item for item in QUALIFIERS if item in folded}


def _primary_artist(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return _normalize(str(value or "").split(",")[0].split("&")[0])


def validate_track(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LyricsProviderError("Track metadata must be an object")
    track: dict[str, Any] = {}
    for key in ("key", "amazonId", "marketplace", "title", "album", "artworkUrl", "isrc"):
        value = str(raw.get(key, "")).strip()
        if len(value) > 2048:
            raise LyricsProviderError(f"Track {key} is too long")
        track[key] = value
    artists = raw.get("artists", [])
    if isinstance(artists, str):
        artists = [artists]
    if not isinstance(artists, list):
        artists = []
    track["artists"] = [str(item).strip()[:512] for item in artists[:20] if str(item).strip()]
    try:
        track["durationMs"] = max(0, min(24 * 60 * 60 * 1000, int(raw.get("durationMs", 0))))
    except (TypeError, ValueError):
        track["durationMs"] = 0
    if not track["key"] or not track["title"] or not track["artists"]:
        raise LyricsProviderError("Track metadata is incomplete")
    return track


class LyricsProviderService:
    def __init__(
        self,
        state_dir: Path,
        *,
        auth: SpotifyAuth | None = None,
        cache: LyricsCache | None = None,
        opener: urllib.request.OpenerDirector | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.auth = auth or SpotifyAuth(state_dir)
        self.cache = cache or LyricsCache(state_dir / "lyrics-cache.sqlite3")
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects()
        )
        self._sleep = sleep
        self._lock = threading.RLock()
        self._requests: dict[str, threading.Event] = {}
        self._closed = False

    def status(self) -> dict[str, Any]:
        status = self.auth.status()
        return {"ok": True, "provider": "spicy-lyrics", "spotify": status}

    def begin_auth(self) -> dict[str, Any]:
        return {"ok": True, "provider": "spicy-lyrics", "spotify": self.auth.begin_auth()}

    def disconnect(self) -> dict[str, Any]:
        return {"ok": True, "provider": "spicy-lyrics", "spotify": self.auth.disconnect()}

    def clear_cache(self) -> dict[str, Any]:
        self.cache.clear()
        return {"ok": True, "cleared": True}

    def cancel(self, request_key: str) -> dict[str, Any]:
        with self._lock:
            event = self._requests.get(request_key)
            if event is not None:
                event.set()
        return {"ok": True, "canceled": bool(event)}

    def load(self, raw_track: dict[str, Any], request_key: str) -> dict[str, Any]:
        track = validate_track(raw_track)
        request_key = str(request_key or "").strip()
        if not request_key or len(request_key) > 256:
            raise LyricsProviderError("Lyrics request key is invalid")
        canceled = threading.Event()
        with self._lock:
            if self._closed:
                raise LyricsProviderError("Lyrics provider is closed")
            previous = self._requests.get(request_key)
            if previous is not None:
                previous.set()
            self._requests[request_key] = canceled
        try:
            spotify_id = self._resolve(track, canceled)
            self._raise_if_canceled(canceled)
            if not spotify_id:
                return {"ok": True, "status": "unresolved", "trackKey": track["key"]}
            cached = self.cache.get_lyrics("spicy-lyrics", spotify_id)
            if cached is not None:
                return {
                    "ok": True,
                    "status": cached["status"],
                    "trackKey": track["key"],
                    "spotifyTrackId": spotify_id,
                    "payload": cached.get("payload"),
                    "cached": True,
                }
            payload = self._load_spicy(spotify_id, canceled)
            self._raise_if_canceled(canceled)
            if payload is None:
                self.cache.store_no_lyrics("spicy-lyrics", spotify_id, SPICY_VERSION)
                return {
                    "ok": True,
                    "status": "no-lyrics",
                    "trackKey": track["key"],
                    "spotifyTrackId": spotify_id,
                }
            self.cache.store_lyrics("spicy-lyrics", spotify_id, payload, SPICY_VERSION)
            return {
                "ok": True,
                "status": "ready",
                "trackKey": track["key"],
                "spotifyTrackId": spotify_id,
                "payload": payload,
                "cached": False,
            }
        except SpotifyAuthError as exc:
            return {"ok": True, "status": "authentication-required", "trackKey": track["key"], "detail": str(exc)}
        except LyricsUnavailable as exc:
            return {"ok": True, "status": "unavailable", "trackKey": track["key"], "detail": str(exc)}
        finally:
            should_finish = False
            with self._lock:
                if self._requests.get(request_key) is canceled:
                    self._requests.pop(request_key, None)
                should_finish = self._closed and not self._requests
            if should_finish:
                self.finish_close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pending = list(self._requests.values())
        for event in pending:
            event.set()
        self.auth.close()
        if not pending:
            self.finish_close()

    def finish_close(self) -> None:
        self.cache.close()

    def _resolve(self, track: dict[str, Any], canceled: threading.Event) -> str:
        cached = self.cache.get_mapping(track["key"], RESOLVER_VERSION)
        if cached:
            return str(cached["spotifyTrackId"])
        token = self.auth.access_token()
        refreshed_search_token = False
        queries: list[tuple[str, str]] = []
        if track["isrc"]:
            queries.append(("isrc", f'isrc:"{track["isrc"]}"'))
        title = track["title"]
        artist = track["artists"][0]
        queries.append(("exact", f'track:"{title}" artist:"{artist}"'))
        if track["album"]:
            queries.append(("album", f'track:"{title}" artist:"{artist}" album:"{track["album"]}"'))
        queries.append(("duration", f'{title} {artist}'))
        for evidence_type, query in queries:
            self._raise_if_canceled(canceled)
            try:
                candidates = self._spotify_search(query, token)
            except urllib.error.HTTPError as exc:
                if exc.code != 401 or refreshed_search_token:
                    raise
                refreshed_search_token = True
                self.auth.invalidate_access_token()
                token = self.auth.access_token(force_refresh=True)
                candidates = self._spotify_search(query, token)
            matches = [item for item in candidates if self._candidate_matches(track, item, evidence_type == "isrc")]
            if len(matches) != 1:
                continue
            spotify_id = str(matches[0].get("id", ""))
            if spotify_id:
                self.cache.store_mapping(
                    track["key"], spotify_id, 1.0,
                    {"method": evidence_type}, RESOLVER_VERSION,
                )
                return spotify_id
        return ""

    def _candidate_matches(self, track: dict[str, Any], item: dict[str, Any], isrc_query: bool) -> bool:
        if not isinstance(item, dict):
            return False
        candidate_title = str(item.get("name", ""))
        if _normalize(candidate_title) != _normalize(track["title"]):
            return False
        track_qualifiers = _qualifiers(track["title"])
        if _qualifiers(candidate_title) != track_qualifiers:
            return False
        artists = item.get("artists", [])
        candidate_artist = artists[0].get("name", "") if isinstance(artists, list) and artists and isinstance(artists[0], dict) else ""
        if _primary_artist(candidate_artist) != _primary_artist(track["artists"]):
            return False
        external_ids = item.get("external_ids", {}) if isinstance(item.get("external_ids"), dict) else {}
        if isrc_query and track["isrc"]:
            return str(external_ids.get("isrc", "")).casefold() == track["isrc"].casefold()
        try:
            difference = abs(int(item.get("duration_ms", 0)) - track["durationMs"])
        except (TypeError, ValueError):
            return False
        return bool(track["durationMs"] and difference <= 5000)

    def _spotify_search(self, query: str, token: str) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"q": query, "type": "track", "limit": "10"})
        payload, _ = self._json_request(
            f"{SPOTIFY_SEARCH_URL}?{params}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        tracks = payload.get("tracks", {}) if isinstance(payload, dict) else {}
        items = tracks.get("items", []) if isinstance(tracks, dict) else []
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _load_spicy(self, spotify_id: str, canceled: threading.Event) -> Any | None:
        refreshed = False
        delays = [0, 1, 2, 4, 8]
        for delay in delays:
            if delay:
                self._sleep(delay + random.uniform(0, min(0.25, delay / 10)))
            self._raise_if_canceled(canceled)
            token = self.auth.access_token(force_refresh=refreshed)
            body = json.dumps({
                "queries": [{"operation": "lyrics", "variables": {"id": spotify_id, "auth": "SpicyLyrics-WebAuth"}}],
                "client": {"version": SPICY_VERSION},
            }, separators=(",", ":")).encode("utf-8")
            try:
                payload, status = self._json_request(
                    SPICY_QUERY_URL,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "SpicyLyrics-Version": SPICY_VERSION,
                        "SpicyLyrics-WebAuth": f"Bearer {token}",
                        "X-mode": "2",
                    },
                    timeout=10,
                )
            except urllib.error.HTTPError as exc:
                status = exc.code
                payload = {}
                if status == 401 and not refreshed:
                    refreshed = True
                    self.auth.invalidate_access_token()
                    continue
                if status == 404:
                    return None
                if status == 503:
                    continue
                if status == 403:
                    raise LyricsUnavailable("Spotify user is not allowlisted for the beta provider") from exc
                if status == 429:
                    retry_after = min(8, max(1, int(exc.headers.get("Retry-After", "1") or 1)))
                    self._sleep(retry_after)
                    continue
                raise LyricsUnavailable(f"Lyrics provider failed ({status})") from exc
            query = payload.get("queries", [None])[0] if isinstance(payload, dict) else None
            result = query.get("result", query) if isinstance(query, dict) else None
            try:
                query_status = int(result.get("httpStatus", status)) if isinstance(result, dict) else status
            except (TypeError, ValueError) as exc:
                raise LyricsProviderError("Lyrics provider response status was malformed") from exc
            if query_status == 404:
                return None
            if query_status != 200 or not isinstance(result, dict) or "data" not in result:
                raise LyricsUnavailable("Lyrics provider returned no compatible lyrics")
            return result["data"]
        raise LyricsUnavailable("Lyrics provider is temporarily unavailable")

    def _json_request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[dict[str, Any], int]:
        parsed = urllib.parse.urlsplit(url)
        allowed = {
            ("api.spotify.com", "/v1/search"),
            ("api.spicylyrics.org", "/query"),
        }
        if parsed.scheme != "https" or (parsed.hostname or "", parsed.path) not in allowed or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise LyricsProviderError("Provider endpoint is not allowed")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            response = self._opener.open(request, timeout=timeout)
            with response:
                if response.geturl() != url:
                    raise LyricsProviderError("Provider endpoint redirected unexpectedly")
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if "application/json" not in content_type:
                    raise LyricsProviderError("Provider returned an invalid content type")
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_NETWORK_BYTES:
                    raise LyricsProviderError("Provider response was too large")
                raw = response.read(MAX_NETWORK_BYTES + 1)
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError:
            raise
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise LyricsUnavailable("Provider network request failed") from exc
        if len(raw) > MAX_NETWORK_BYTES:
            raise LyricsProviderError("Provider response was too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LyricsProviderError("Provider response was malformed") from exc
        if not isinstance(payload, dict):
            raise LyricsProviderError("Provider response was malformed")
        return payload, status

    @staticmethod
    def _raise_if_canceled(event: threading.Event) -> None:
        if event.is_set():
            raise LyricsUnavailable("Lyrics request was canceled")
