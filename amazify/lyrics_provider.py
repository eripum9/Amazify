from __future__ import annotations

import hashlib
import http.client
import json
import math
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
from .rich_lyrics import RichLyricsError, parse_ttml, validate_model


BETTER_LYRICS_URL = "https://lyrics-api.boidu.dev/getLyrics"
UNISON_URL = "https://unison.boidu.dev/lyrics"
PROVIDER_VERSION = "native-rich-v1"
MAX_NETWORK_BYTES = 1 * 1024 * 1024
MAX_REQUEST_SECONDS = 24.0
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_CONCURRENT_REQUESTS = 2
MIN_BETTER_SCORE = 80.0
QUALIFIERS = frozenset(
    {"live", "remix", "acoustic", "instrumental", "karaoke", "remaster", "sped up", "slowed"}
)


class LyricsProviderError(RuntimeError):
    pass


class LyricsUnavailable(LyricsProviderError):
    pass


class _Canceled(LyricsUnavailable):
    pass


class _ProviderMiss(Exception):
    pass


class _ProviderMalformed(Exception):
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


def _strip_explicit(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\s*[\[(]\s*explicit\s*[\])]", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _strip_explicit(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def _qualifiers(value: Any) -> set[str]:
    folded = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return {
        item for item in QUALIFIERS
        if re.search(rf"(?<![a-z0-9]){re.escape(item)}(?![a-z0-9])", folded)
    }


def _primary_artist(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return _normalize(value)


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


def _metadata_fingerprint(track: dict[str, Any]) -> str:
    relevant = {
        "key": track["key"],
        "title": track["title"],
        "artists": track["artists"],
        "album": track["album"],
        "durationMs": track["durationMs"],
        "isrc": track["isrc"],
        "providerVersion": PROVIDER_VERSION,
    }
    encoded = json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata_matches(track: dict[str, Any], data: dict[str, Any]) -> bool:
    title = data.get("song", data.get("title", ""))
    artist = data.get("artist", data.get("artists", ""))
    if not title or _normalize(title) != _normalize(track["title"]):
        return False
    if not artist or _primary_artist(artist) != _primary_artist(track["artists"]):
        return False
    if _qualifiers(title) != _qualifiers(track["title"]):
        return False
    album = data.get("album", "")
    if track["album"] and album and _normalize(album) != _normalize(track["album"]):
        return False
    if track["durationMs"] and data.get("duration") not in (None, ""):
        try:
            duration = float(data["duration"])
            if not math.isfinite(duration) or abs(duration - track["durationMs"] / 1000) > 5:
                return False
        except (TypeError, ValueError):
            return False
    return True


class LyricsProviderService:
    def __init__(
        self,
        state_dir: Path,
        *,
        cache: LyricsCache | None = None,
        opener: urllib.request.OpenerDirector | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache = cache or LyricsCache(state_dir / "lyrics-cache.sqlite3")
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects()
        )
        self._sleep = sleep
        self._clock = clock
        self._network_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self._lock = threading.RLock()
        self._requests: dict[str, threading.Event] = {}
        self._closed = False
        self._cache_closed = False

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": "better-lyrics",
            "providers": ["better-lyrics", "unison"],
            "authenticated": False,
        }

    def clear_cache(self) -> dict[str, Any]:
        self.cache.clear()
        return {"ok": True, "cleared": True}

    def cancel(self, request_key: str) -> dict[str, Any]:
        with self._lock:
            event = self._requests.get(str(request_key or ""))
            if event is not None:
                event.set()
        return {"ok": True, "canceled": bool(event)}

    def load(self, raw_track: dict[str, Any], request_key: str, *, cancel_event: threading.Event | None = None) -> dict[str, Any]:
        track = validate_track(raw_track)
        request_key = str(request_key or "").strip()
        if not request_key or len(request_key) > 256:
            raise LyricsProviderError("Lyrics request key is invalid")
        canceled = cancel_event if cancel_event is not None else threading.Event()
        with self._lock:
            if self._closed:
                raise LyricsProviderError("Lyrics provider is closed")
            previous = self._requests.get(request_key)
            if previous is not None:
                previous.set()
            self._requests[request_key] = canceled
        fingerprint = _metadata_fingerprint(track)
        deadline = self._clock() + MAX_REQUEST_SECONDS
        try:
            cached = self._cached_result(track, fingerprint)
            self._raise_if_canceled(canceled)
            for result in cached:
                if result["status"] == "ready":
                    return result
            outcomes: list[tuple[str, str]] = [(item["source"], item["status"]) for item in cached]
            for provider in ("better-lyrics", "unison"):
                self._raise_if_canceled(canceled)
                if any(item["source"] == provider for item in cached):
                    continue
                try:
                    payload = self._load_provider(provider, track, canceled, deadline)
                except _ProviderMiss:
                    self._raise_if_canceled(canceled)
                    outcomes.append((provider, "no-lyrics"))
                    self.cache.store_no_lyrics(provider, fingerprint, f"{PROVIDER_VERSION}:{fingerprint}")
                    continue
                except (_ProviderMalformed, LyricsUnavailable):
                    self._raise_if_canceled(canceled)
                    outcomes.append((provider, "unavailable"))
                    continue
                self._raise_if_canceled(canceled)
                self.cache.store_lyrics(provider, fingerprint, payload, f"{PROVIDER_VERSION}:{fingerprint}")
                return self._result("ready", track, provider, payload, False)
            self._raise_if_canceled(canceled)
            status = "no-lyrics" if outcomes and all(status == "no-lyrics" for _, status in outcomes) else "unavailable"
            source = next((source for source, item_status in outcomes if item_status == status), "better-lyrics")
            detail = "No compatible rich lyrics" if status == "no-lyrics" else "Providers unavailable"
            cached_outcome = any(
                item["source"] == source and item["status"] == status and item["cached"]
                for item in cached
            )
            return self._result(status, track, source, None, cached_outcome, detail)
        except _Canceled as exc:
            return self._result("unavailable", track, "better-lyrics", None, False, str(exc))
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
        if not pending:
            self.finish_close()

    def finish_close(self) -> None:
        with self._lock:
            if not self._cache_closed:
                self._cache_closed = True
                self.cache.close()

    def _cached_result(self, track: dict[str, Any], fingerprint: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        version = f"{PROVIDER_VERSION}:{fingerprint}"
        for provider in ("better-lyrics", "unison"):
            cached = self.cache.get_lyrics(provider, fingerprint)
            if cached is None or cached.get("providerVersion") != version:
                continue
            status = str(cached.get("status", ""))
            payload = cached.get("payload")
            if status == "ready":
                if not isinstance(payload, dict) or not validate_model(payload) or payload.get("trackKey") != track["key"]:
                    continue
                results.append(self._result("ready", track, provider, payload, True))
            elif status == "no-lyrics":
                results.append(self._result("no-lyrics", track, provider, None, True))
        return results

    @staticmethod
    def _result(
        status: str,
        track: dict[str, Any],
        source: str,
        payload: dict[str, Any] | None,
        cached: bool,
        detail: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": True,
            "status": status,
            "trackKey": track["key"],
            "payload": payload,
            "source": source,
            "cached": cached,
        }
        if detail:
            result["detail"] = detail
        return result

    def _load_provider(
        self,
        provider: str,
        track: dict[str, Any],
        canceled: threading.Event,
        deadline: float,
    ) -> dict[str, Any]:
        if provider == "better-lyrics":
            params = {"s": _strip_explicit(track["title"]), "a": _strip_explicit(track["artists"][0])}
            if track["album"]:
                params["al"] = _strip_explicit(track["album"])
            if track["durationMs"]:
                params["d"] = f"{track['durationMs'] / 1000:g}"
            payload = self._get_json(BETTER_LYRICS_URL, params, canceled, deadline)
            if not isinstance(payload.get("ttml"), str) or not payload["ttml"].strip():
                raise _ProviderMiss("Better Lyrics has no TTML")
            score = payload.get("score")
            score_value: float | None = None
            if score is None or score == "":
                score_value = None
            elif isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
                score_value = float(score)
            else:
                raise _ProviderMalformed("Better Lyrics score is malformed")
            if score_value is not None and not MIN_BETTER_SCORE <= score_value <= 100:
                raise _ProviderMiss("Better Lyrics confidence is low")
            try:
                return parse_ttml(payload["ttml"], source=provider, track_key=track["key"])
            except RichLyricsError as exc:
                raise _ProviderMalformed(str(exc)) from exc
        if provider == "unison":
            params = {"song": _strip_explicit(track["title"]), "artist": _strip_explicit(track["artists"][0])}
            if track["album"]:
                params["album"] = _strip_explicit(track["album"])
            if track["durationMs"]:
                params["duration"] = f"{track['durationMs'] / 1000:g}"
            response = self._get_json(UNISON_URL, params, canceled, deadline)
            if response.get("success") is not True or not isinstance(response.get("data"), dict):
                raise _ProviderMiss("Unison has no lyrics")
            data = response["data"]
            if not _metadata_matches(track, data):
                raise _ProviderMalformed("Unison metadata did not match")
            confidence = data.get("confidence")
            if isinstance(confidence, str) and confidence.casefold() == "low":
                raise _ProviderMiss("Unison confidence is low")
            lyrics = data.get("lyrics")
            format_name = str(data.get("format", "")).casefold()
            sync_type = str(data.get("syncType", "")).casefold()
            if not isinstance(lyrics, str) or format_name not in {"ttml", "xml"} or sync_type not in {"", "richsync"}:
                raise _ProviderMiss("Unison response is not rich TTML")
            try:
                return parse_ttml(
                    lyrics,
                    source=provider,
                    track_key=track["key"],
                    language=str(data.get("language", "")) or None,
                )
            except RichLyricsError as exc:
                raise _ProviderMalformed(str(exc)) from exc
        raise LyricsProviderError("Unknown lyrics provider")

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, str],
        canceled: threading.Event,
        deadline: float,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(params, doseq=False, safe="")
        url = f"{endpoint}?{query}"
        for attempt in range(2):
            self._raise_if_canceled(canceled)
            try:
                return self._json_request(url, canceled=canceled, deadline=deadline)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise _ProviderMiss("Provider has no lyrics") from exc
                if exc.code == 401:
                    raise LyricsUnavailable("Provider requires authentication") from exc
                if exc.code == 429 and attempt == 0:
                    retry_after = 0.5
                    try:
                        headers = exc.headers or {}
                        retry_after = min(1.0, max(0.0, float(headers.get("Retry-After", "0.5"))))
                    except (TypeError, ValueError):
                        pass
                    self._sleep(retry_after)
                    continue
                if 500 <= exc.code <= 599:
                    raise LyricsUnavailable(f"Provider failed ({exc.code})") from exc
                raise _ProviderMalformed(f"Provider returned HTTP {exc.code}") from exc
        raise LyricsUnavailable("Provider rate limit persisted")

    def _json_request(self, url: str, *, canceled: threading.Event, deadline: float) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise LyricsProviderError("Provider endpoint is not allowed") from exc
        allowed = {("lyrics-api.boidu.dev", "/getLyrics"), ("unison.boidu.dev", "/lyrics")}
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "", parsed.path) not in allowed
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise LyricsProviderError("Provider endpoint is not allowed")
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise LyricsUnavailable("Provider request deadline exceeded")
        acquired = self._network_slots.acquire(timeout=min(remaining, REQUEST_TIMEOUT_SECONDS))
        if not acquired:
            raise LyricsUnavailable("Provider request capacity is busy")
        try:
            self._raise_if_canceled(canceled)
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise LyricsUnavailable("Provider request deadline exceeded")
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "Amazify-Karaoke-Lyrics/0.2"},
                method="GET",
            )
            response = self._opener.open(request, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining))
            with response:
                if response.geturl() != url:
                    raise _ProviderMalformed("Provider endpoint redirected unexpectedly")
                content_type = str(response.headers.get("Content-Type", "")).casefold()
                if content_type.split(";", 1)[0].strip() != "application/json":
                    raise _ProviderMalformed("Provider returned an invalid content type")
                length = response.headers.get("Content-Length")
                try:
                    if length and int(length) > MAX_NETWORK_BYTES:
                        raise _ProviderMalformed("Provider response was too large")
                except ValueError as exc:
                    raise _ProviderMalformed("Provider content length was malformed") from exc
                chunks: list[bytes] = []
                total = 0
                while True:
                    self._raise_if_canceled(canceled)
                    if self._clock() >= deadline:
                        raise LyricsUnavailable("Provider response deadline exceeded")
                    read = getattr(response, "read1", response.read)
                    chunk = read(min(16 * 1024, MAX_NETWORK_BYTES + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_NETWORK_BYTES:
                        raise _ProviderMalformed("Provider response was too large")
                raw = b"".join(chunks)
        except urllib.error.HTTPError:
            raise
        except (_ProviderMalformed, _Canceled):
            raise
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise LyricsUnavailable("Provider network request failed") from exc
        finally:
            self._network_slots.release()
        try:
            def reject_constant(value: str) -> None:
                raise ValueError("Non-finite JSON value")
            payload = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise _ProviderMalformed("Provider response was malformed") from exc
        if not isinstance(payload, dict):
            raise _ProviderMalformed("Provider response was malformed")
        stack: list[tuple[Any, int]] = [(payload, 0)]
        nodes = 0
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > 10000 or depth > 32:
                raise _ProviderMalformed("Provider JSON exceeded structural limits")
            if isinstance(value, dict):
                stack.extend((child, depth + 1) for child in value.values())
            elif isinstance(value, list):
                stack.extend((child, depth + 1) for child in value)
        return payload

    @staticmethod
    def _raise_if_canceled(event: threading.Event) -> None:
        if event.is_set():
            raise _Canceled("Lyrics request was canceled")
