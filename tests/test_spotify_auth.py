from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from amazify.spotify_auth import DpapiTokenStore, SpotifyAuth


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class DpapiTokenStoreTests(unittest.TestCase):
    def test_round_trip_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = DpapiTokenStore(Path(temp) / "token.bin")
            store.save("refresh-token-value")
            self.assertEqual(store.load(), "refresh-token-value")
            self.assertNotIn(b"refresh-token-value", store.path.read_bytes())
            store.clear()
            self.assertEqual(store.load(), "")


class MemoryTokenStore:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def load(self) -> str:
        return self.value

    def save(self, value: str) -> None:
        self.value = value

    def clear(self) -> None:
        self.value = ""


class SpotifyAuthTests(unittest.TestCase):
    def test_refresh_keeps_rotated_refresh_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryTokenStore("old-refresh")
            auth = SpotifyAuth(Path(temp), client_id="public", token_store=store)  # type: ignore[arg-type]
            auth._request_token = lambda form: {  # type: ignore[method-assign]
                "access_token": "access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }
            self.assertEqual(auth.access_token(), "access")
            self.assertEqual(store.value, "new-refresh")

    def test_unconfigured_status_does_not_expose_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            auth = SpotifyAuth(Path(temp), client_id="", token_store=MemoryTokenStore())  # type: ignore[arg-type]
            self.assertEqual(auth.status()["state"], "unconfigured")
            self.assertNotIn("token", str(auth.status()).lower())


if __name__ == "__main__":
    unittest.main()
