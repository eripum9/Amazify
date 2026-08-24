from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from amazify.lyrics_cache import LyricsCache
from amazify.lyrics_provider import LyricsProviderError, LyricsProviderService, validate_track


class StubAuth:
    def access_token(self, *, force_refresh: bool = False) -> str:
        return "token"

    def status(self):
        return {"state": "connected"}

    def close(self) -> None:
        pass


class LyricsProviderTests(unittest.TestCase):
    def make_service(self, root: Path) -> LyricsProviderService:
        return LyricsProviderService(
            root,
            auth=StubAuth(),  # type: ignore[arg-type]
            cache=LyricsCache(root / "cache.sqlite3"),
            sleep=lambda value: None,
        )

    def test_rejects_incomplete_track(self) -> None:
        with self.assertRaises(LyricsProviderError):
            validate_track({"key": "track", "title": "Title", "artists": []})

    def test_ambiguous_resolution_returns_no_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp))
            candidate = {
                "id": "spotify",
                "name": "Song",
                "artists": [{"name": "Artist"}],
                "duration_ms": 180000,
                "external_ids": {},
            }
            service._spotify_search = lambda query, token: [candidate, dict(candidate, id="other")]  # type: ignore[method-assign]
            track = validate_track({"key": "amazon:key", "title": "Song", "artists": ["Artist"], "durationMs": 180000})
            self.assertEqual(service._resolve(track, threading.Event()), "")
            service.close()

    def test_conflicting_qualifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp))
            track = validate_track({"key": "amazon:key", "title": "Song", "artists": ["Artist"], "durationMs": 180000})
            candidate = {"id": "spotify", "name": "Song (Live)", "artists": [{"name": "Artist"}], "duration_ms": 180000}
            self.assertFalse(service._candidate_matches(track, candidate, False))
            service.close()

    def test_endpoint_allowlist_rejects_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = self.make_service(Path(temp))
            with self.assertRaises(LyricsProviderError):
                service._json_request("https://example.com/query", headers={}, timeout=1)
            service.close()


if __name__ == "__main__":
    unittest.main()
