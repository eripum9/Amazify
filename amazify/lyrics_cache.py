from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
MAX_CACHE_BYTES = 64 * 1024 * 1024
MAPPING_TTL_SECONDS = 90 * 24 * 60 * 60
LYRICS_TTL_SECONDS = 7 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 24 * 60 * 60
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024


class LyricsCache:
    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], float] = time.time,
        max_bytes: int = MAX_CACHE_BYTES,
    ) -> None:
        self.path = path
        self._now = now
        self._max_bytes = max_bytes
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        self._connection: sqlite3.Connection | None = connection
        with self._lock:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS track_mapping (
                    amazon_key TEXT PRIMARY KEY,
                    spotify_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    resolver_version INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    last_accessed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lyrics_payload (
                    provider TEXT NOT NULL,
                    provider_track_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json BLOB,
                    provider_version TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    PRIMARY KEY (provider, provider_track_id)
                );
                """
            )
            stored = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if stored is not None and stored["value"] != str(SCHEMA_VERSION):
                connection.execute("DELETE FROM track_mapping")
                connection.execute("DELETE FROM lyrics_payload")
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()

    def get_mapping(self, amazon_key: str, resolver_version: int) -> dict[str, Any] | None:
        now = self._now()
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                """
                SELECT spotify_id, score, evidence_json
                FROM track_mapping
                WHERE amazon_key = ? AND resolver_version = ? AND expires_at > ?
                """,
                (amazon_key, resolver_version, now),
            ).fetchone()
            if row is None:
                connection.execute(
                    "DELETE FROM track_mapping WHERE amazon_key = ?", (amazon_key,)
                )
                connection.commit()
                return None
            connection.execute(
                "UPDATE track_mapping SET last_accessed = ? WHERE amazon_key = ?",
                (now, amazon_key),
            )
            connection.commit()
            try:
                evidence = json.loads(row["evidence_json"])
            except (TypeError, json.JSONDecodeError):
                evidence = {}
            return {
                "spotifyTrackId": row["spotify_id"],
                "score": float(row["score"]),
                "evidence": evidence if isinstance(evidence, dict) else {},
                "cached": True,
            }

    def store_mapping(
        self,
        amazon_key: str,
        spotify_id: str,
        score: float,
        evidence: dict[str, Any],
        resolver_version: int,
    ) -> None:
        now = self._now()
        encoded = json.dumps(evidence, separators=(",", ":"), sort_keys=True)
        with self._lock:
            connection = self._require_connection()
            connection.execute(
                """
                INSERT OR REPLACE INTO track_mapping(
                    amazon_key, spotify_id, score, evidence_json,
                    resolver_version, expires_at, last_accessed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    amazon_key,
                    spotify_id,
                    float(score),
                    encoded,
                    resolver_version,
                    now + MAPPING_TTL_SECONDS,
                    now,
                ),
            )
            connection.commit()
            self._prune_locked()

    def get_lyrics(self, provider: str, track_id: str) -> dict[str, Any] | None:
        now = self._now()
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                """
                SELECT status, payload_json, provider_version
                FROM lyrics_payload
                WHERE provider = ? AND provider_track_id = ? AND expires_at > ?
                """,
                (provider, track_id, now),
            ).fetchone()
            if row is None:
                connection.execute(
                    "DELETE FROM lyrics_payload WHERE provider = ? AND provider_track_id = ?",
                    (provider, track_id),
                )
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE lyrics_payload SET last_accessed = ?
                WHERE provider = ? AND provider_track_id = ?
                """,
                (now, provider, track_id),
            )
            connection.commit()
            payload: Any = None
            if row["payload_json"] is not None:
                try:
                    payload = json.loads(bytes(row["payload_json"]).decode("utf-8"))
                except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
                    return None
            return {
                "status": row["status"],
                "payload": payload,
                "providerVersion": row["provider_version"],
                "cached": True,
            }

    def store_lyrics(
        self,
        provider: str,
        track_id: str,
        payload: Any,
        provider_version: str,
    ) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValueError("Lyrics payload exceeds cache limit")
        self._store_lyrics_row(
            provider,
            track_id,
            status="ready",
            payload=encoded,
            provider_version=provider_version,
            ttl=LYRICS_TTL_SECONDS,
        )

    def store_no_lyrics(
        self, provider: str, track_id: str, provider_version: str
    ) -> None:
        self._store_lyrics_row(
            provider,
            track_id,
            status="no-lyrics",
            payload=None,
            provider_version=provider_version,
            ttl=NEGATIVE_TTL_SECONDS,
        )

    def _store_lyrics_row(
        self,
        provider: str,
        track_id: str,
        *,
        status: str,
        payload: bytes | None,
        provider_version: str,
        ttl: int,
    ) -> None:
        now = self._now()
        with self._lock:
            connection = self._require_connection()
            connection.execute(
                """
                INSERT OR REPLACE INTO lyrics_payload(
                    provider, provider_track_id, status, payload_json,
                    provider_version, expires_at, last_accessed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    track_id,
                    status,
                    payload,
                    provider_version,
                    now + ttl,
                    now,
                ),
            )
            connection.commit()
            self._prune_locked()

    def clear(self) -> None:
        with self._lock:
            connection = self._require_connection()
            connection.execute("DELETE FROM track_mapping")
            connection.execute("DELETE FROM lyrics_payload")
            connection.commit()
            connection.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("Lyrics cache is closed")
        return connection

    def _prune_locked(self) -> None:
        now = self._now()
        connection = self._require_connection()
        connection.execute("DELETE FROM track_mapping WHERE expires_at <= ?", (now,))
        connection.execute("DELETE FROM lyrics_payload WHERE expires_at <= ?", (now,))
        connection.commit()
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        removed = False
        while True:
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            used_size = max(0, page_count - free_pages) * page_size
            if used_size <= self._max_bytes:
                break
            row = connection.execute(
                """
                SELECT provider, provider_track_id FROM lyrics_payload
                ORDER BY last_accessed ASC LIMIT 1
                """
            ).fetchone()
            if row is not None:
                connection.execute(
                    "DELETE FROM lyrics_payload WHERE provider = ? AND provider_track_id = ?",
                    (row["provider"], row["provider_track_id"]),
                )
            else:
                mapping = connection.execute(
                    "SELECT amazon_key FROM track_mapping ORDER BY last_accessed ASC LIMIT 1"
                ).fetchone()
                if mapping is None:
                    break
                connection.execute(
                    "DELETE FROM track_mapping WHERE amazon_key = ?",
                    (mapping["amazon_key"],),
                )
            connection.commit()
            removed = True
        if removed:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")
