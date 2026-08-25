from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amazify.lyrics_cache import LyricsCache, LYRICS_TTL_SECONDS


class LyricsCacheTests(unittest.TestCase):
    def test_mapping_and_payload_expire(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            clock = [1000.0]
            cache = LyricsCache(Path(temp) / "lyrics.sqlite3", now=lambda: clock[0])
            cache.store_mapping("amazon:key", "spotify-id", 1, {"method": "isrc"}, 1)
            cache.store_lyrics("spicy-lyrics", "spotify-id", {"value": 1}, "1.1")
            self.assertEqual(cache.get_mapping("amazon:key", 1)["spotifyTrackId"], "spotify-id")
            self.assertEqual(cache.get_lyrics("spicy-lyrics", "spotify-id")["payload"], {"value": 1})
            clock[0] += LYRICS_TTL_SECONDS + 1
            self.assertIsNone(cache.get_lyrics("spicy-lyrics", "spotify-id"))
            cache.close()

    def test_schema_version_mismatch_clears_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lyrics.sqlite3"
            cache = LyricsCache(path)
            cache.store_mapping("amazon:key", "spotify-id", 1, {}, 1)
            connection = cache._require_connection()
            connection.execute(
                "UPDATE metadata SET value = '999' WHERE key = 'schema_version'"
            )
            connection.commit()
            cache.close()
            reopened = LyricsCache(path)
            self.assertIsNone(reopened.get_mapping("amazon:key", 1))
            reopened.close()

    def test_size_limit_evicts_least_recently_used_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache = LyricsCache(Path(temp) / "lyrics.sqlite3", max_bytes=360_000)
            payload = {"lyrics": "x" * 220_000}
            cache.store_lyrics("spicy-lyrics", "old", payload, "1.1")
            cache.store_lyrics("spicy-lyrics", "new", payload, "1.1")
            self.assertIsNone(cache.get_lyrics("spicy-lyrics", "old"))
            self.assertEqual(cache.get_lyrics("spicy-lyrics", "new")["payload"], payload)
            cache.close()

    def test_operations_after_close_fail_predictably(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache = LyricsCache(Path(temp) / "lyrics.sqlite3")
            cache.close()
            cache.close()

            with self.assertRaisesRegex(RuntimeError, "Lyrics cache is closed"):
                cache.get_mapping("amazon:key", 1)


if __name__ == "__main__":
    unittest.main()
