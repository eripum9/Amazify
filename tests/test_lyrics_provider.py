from __future__ import annotations

import json
from email.message import Message
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from typing import Any

from amazify.lyrics_cache import LyricsCache
from amazify.lyrics_provider import LyricsProviderError, LyricsProviderService, validate_track, _metadata_matches


RICH_TTML = """<?xml version="1.0"?>
<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="en">
  <body><div>
    <p begin="00:00:01.000" end="00:00:03.000">
      <span begin="00:00:01.000" end="00:00:01.400">Hel</span>
      <span begin="00:00:01.400" end="00:00:01.900">lo </span>
      <span begin="00:00:02.000" end="00:00:02.900">world</span>
    </p>
  </div></body>
</tt>"""


class FakeResponse:
    def __init__(self, body: bytes, url: str, content_type: str = "application/json") -> None:
        self.body = body
        self.url = url
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def geturl(self) -> str:
        return self.url

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self.body)
        value, self.body = self.body[:amount], self.body[amount:]
        return value


class FakeOpener:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, str]]] = []

    def open(self, request: Any, timeout: float = 0) -> Any:
        self.requests.append((request.full_url, dict(request.header_items())))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(json.dumps(response).encode("utf-8"), request.full_url)


def track(**overrides: Any) -> dict[str, Any]:
    value = {
        "key": "amazon:track-1",
        "title": "Song",
        "artists": ["Artist"],
        "album": "Album",
        "durationMs": 180000,
    }
    value.update(overrides)
    return value


class LyricsProviderTests(unittest.TestCase):
    def make_service(self, root: Path, opener: Any, cache: LyricsCache | None = None) -> LyricsProviderService:
        return LyricsProviderService(
            root,
            opener=opener,
            cache=cache or LyricsCache(root / "cache.sqlite3"),
            sleep=lambda _: None,
        )

    def test_track_validation_and_native_status(self) -> None:
        with self.assertRaises(LyricsProviderError):
            validate_track({"key": "track", "title": "Title", "artists": []})
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), FakeOpener([]))
            self.assertEqual(service.status()["providers"], ["better-lyrics", "unison"])
            self.assertFalse(service.status()["authenticated"])
            service.close()

    def test_better_lyrics_is_first_and_uses_documented_public_query(self) -> None:
        opener = FakeOpener([{"ttml": RICH_TTML, "score": 95}])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source"], "better-lyrics")
            parsed = urllib.parse.urlsplit(opener.requests[0][0])
            self.assertEqual(parsed.hostname, "lyrics-api.boidu.dev")
            self.assertEqual(parsed.path, "/getLyrics")
            self.assertEqual(
                urllib.parse.parse_qs(parsed.query),
                {"s": ["Song"], "a": ["Artist"], "al": ["Album"], "d": ["180"]},
            )
            self.assertNotIn("authorization", {key.casefold() for key in opener.requests[0][1]})
            self.assertNotIn("x-api-key", {key.casefold() for key in opener.requests[0][1]})
            service.close()

    def test_query_strips_only_explicit_tags(self) -> None:
        opener = FakeOpener([{"ttml": RICH_TTML, "score": 95}])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(
                Path(temp),
                opener,
            )
            result = service.load(
                track(
                    title="Jamba [Explicit]",
                    artists=["Tyler, The Creator feat. Hodgy"],
                    album="Wolf + Instrumentals [Explicit]",
                    durationMs=213000,
                ),
                "request-1",
            )
            self.assertEqual(result["status"], "ready")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(opener.requests[0][0]).query)
            self.assertEqual(query["s"], ["Jamba"])
            self.assertEqual(query["a"], ["Tyler, The Creator feat. Hodgy"])
            self.assertEqual(query["al"], ["Wolf + Instrumentals"])
            self.assertEqual(query["d"], ["213"])
            service.close()

    def test_malformed_first_provider_falls_through_to_unison_schema(self) -> None:
        unison = {
            "success": True,
            "data": {
                "song": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration": 180,
                "lyrics": RICH_TTML,
                "format": "ttml",
                "language": "en",
                "syncType": "richsync",
                "confidence": "high",
            },
        }
        opener = FakeOpener([{"ttml": "<tt>line-only</tt>", "score": 95}, unison])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source"], "unison")
            self.assertEqual([urllib.parse.urlsplit(item[0]).hostname for item in opener.requests], [
                "lyrics-api.boidu.dev", "unison.boidu.dev"
            ])
            service.close()

    def test_better_lyrics_missing_score_is_accepted(self) -> None:
        opener = FakeOpener([{"ttml": RICH_TTML, "score": None}])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source"], "better-lyrics")
            service.close()

    def test_malformed_better_score_falls_through_to_unison(self) -> None:
        unison = {
            "success": True,
            "data": {
                "song": "Song",
                "artist": "Artist",
                "album": "Album",
                "duration": 180,
                "lyrics": RICH_TTML,
                "format": "ttml",
                "language": "en",
                "syncType": "richsync",
                "confidence": "high",
            },
        }
        opener = FakeOpener([{"ttml": RICH_TTML, "score": "unknown"}, unison])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source"], "unison")
            service.close()

    def test_unauthenticated_and_no_lyrics_responses_fall_through_without_negative_caching_errors(self) -> None:
        from urllib.error import HTTPError

        unauthorized = HTTPError("https://lyrics-api.boidu.dev/getLyrics", 401, "auth", Message(), None)
        failed = HTTPError("https://unison.boidu.dev/lyrics", 503, "down", Message(), None)
        opener = FakeOpener([unauthorized, failed, unauthorized, failed])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["payload"], None)
            service.load(track(), "request-2")
            self.assertEqual(len(opener.requests), 4)
            service.close()

    def test_unicode_and_artist_punctuation_are_not_ambiguous_matches(self) -> None:
        metadata = track(artists=["Tyler, The Creator"])
        self.assertTrue(_metadata_matches(metadata, {"song": "Song", "artist": "Tyler, The Creator"}))
        self.assertFalse(_metadata_matches(metadata, {"song": "Song", "artist": "Tyler, Someone Else"}))
        self.assertFalse(_metadata_matches(metadata, {"song": "Song"}))
        self.assertFalse(_metadata_matches(track(title="\u4f60\u597d"), {"song": "\u518d\u89c1", "artist": "Artist"}))
        self.assertFalse(_metadata_matches(track(), {"song": "Song", "artist": "Artist", "duration": float("nan")}))

    def test_endpoint_size_mime_redirect_and_malformed_json_restrictions(self) -> None:
        class RawOpener:
            def __init__(self, mode: str) -> None:
                self.mode = mode
            def open(self, request: Any, timeout: float = 0) -> FakeResponse:
                response = FakeResponse(b'{}', request.full_url)
                if self.mode == "redirect": response.url = "https://example.com/lyrics"
                if self.mode == "mime": response.headers["Content-Type"] = "text/html"
                if self.mode == "size": response.headers["Content-Length"] = str(2 * 1024 * 1024)
                if self.mode == "nan": response.body = b'{"score":NaN}'
                if self.mode == "depth": response.body = b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'
                return response
        with tempfile.TemporaryDirectory() as temp:
            for mode in ("redirect", "mime", "size", "nan", "depth"):
                service = self.make_service(Path(temp), RawOpener(mode))
                try:
                    for attempt in range(3):
                        result = service.load(track(), str(attempt))
                        self.assertEqual(result["status"], "unavailable", mode)
                    with self.assertRaises(LyricsProviderError):
                        service._json_request("http://127.0.0.1/lyrics", canceled=threading.Event(), deadline=time.monotonic()+1)
                finally: service.close()

    def test_low_score_and_metadata_qualifier_do_not_relax_fallback(self) -> None:
        unison = {
            "success": True,
            "data": {
                "song": "Song (Live)",
                "artist": "Artist",
                "lyrics": RICH_TTML,
                "format": "ttml",
                "syncType": "richsync",
            },
        }
        opener = FakeOpener([{"ttml": RICH_TTML, "score": 10}, unison])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result = service.load(track(), "request-1")
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(len(opener.requests), 2)
            service.close()

    def test_cache_reuses_positive_payload_and_fingerprint_includes_duration(self) -> None:
        opener = FakeOpener([{"ttml": RICH_TTML, "score": 95}])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = LyricsCache(root / "cache.sqlite3")
            first = self.make_service(root, opener, cache)
            first_result = first.load(track(), "request-1")
            self.assertFalse(first_result["cached"])
            second = self.make_service(root, FakeOpener([]), cache)
            cached_result = second.load(track(), "request-2")
            self.assertTrue(cached_result["cached"])
            self.assertEqual(cached_result["payload"], first_result["payload"])
            changed_opener = FakeOpener([
                {"ttml": "<tt><body><p>line only</p></body></tt>"},
                {"success": False, "data": None},
            ])
            changed = self.make_service(root, changed_opener, cache)
            changed_result = changed.load(track(durationMs=181000), "request-3")
            self.assertEqual(changed_result["status"], "unavailable")
            first.close()
            second.close()
            changed.close()

    def test_cancel_discards_stale_result(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class SlowResponse(FakeResponse):
            def read(self, amount: int = -1) -> bytes:
                started.set()
                release.wait(2)
                return super().read(amount)

        class SlowOpener(FakeOpener):
            def open(self, request: Any, timeout: float = 0) -> Any:
                self.requests.append((request.full_url, dict(request.header_items())))
                return SlowResponse(json.dumps({"ttml": RICH_TTML, "score": 95}).encode(), request.full_url)

        opener = SlowOpener([])
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp), opener)
            result: list[dict[str, Any]] = []
            worker = threading.Thread(target=lambda: result.append(service.load(track(), "request-1")))
            worker.start()
            self.assertTrue(started.wait(1))
            self.assertTrue(service.cancel("request-1")["canceled"])
            release.set()
            worker.join(2)
            self.assertEqual(result[0]["status"], "unavailable")
            service.close()


if __name__ == "__main__":
    unittest.main()
