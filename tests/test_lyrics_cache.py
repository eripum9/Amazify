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
            cache._connection.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
            cache._connection.commit()
            cache.close()
            reopened = LyricsCache(path)
            self.assertIsNone(reopened.get_mapping("amazon:key", 1))
            reopened.close()


if __name__ == "__main__":
    unittest.main()
