# Karaoke Lyrics Provider And Authentication

Karaoke Lyrics always starts with Amazon Music's own `lyricsData` when it is
available. Connecting Spotify is optional and only attempts to upgrade that
fallback to word or syllable timing through the Spicy Lyrics compatibility API.

## Spotify Connection

Amazify uses Authorization Code with PKCE. It opens Spotify in the system
browser, listens temporarily on a random `127.0.0.1` port, validates a random
OAuth state, and requests no scopes. There is no client secret in Amazify.

The public client ID is read from `AMAZIFY_SPOTIFY_CLIENT_ID` in source builds.
Packaged builds receive it from a generated PyInstaller runtime hook. Candidate
builds require the repository Actions variable of the same name.

Access tokens remain in native process memory. Refresh tokens are encrypted with
Windows DPAPI at `%APPDATA%\Amazify\spotify_refresh_token.bin`. Disconnecting
deletes that file. Tokens, callback codes, states, and PKCE verifiers are not
logged and never enter `lyrics-cache.sqlite3`.

Spotify development-mode applications currently restrict access to allowlisted
users. A user outside that list sees a provider-unavailable status and continues
to receive Amazon's line lyrics.

## Track Resolution

Resolution uses a cached mapping, then ISRC, exact title and primary artist,
album metadata, and finally duration comparison. A metadata-only match requires
an exact normalized title and primary artist plus duration within five seconds.
Conflicting qualifiers such as live, remix, acoustic, instrumental, sped-up,
slowed, karaoke, and remaster are rejected. Ambiguous results are never guessed.

## Provider Data

The provider sends `SpicyLyrics-Version`, `SpicyLyrics-WebAuth`, and `X-mode: 2`
to `https://api.spicylyrics.org/query`. This discloses the no-scope Spotify
bearer token to Spicy Lyrics. The implementation is independently written for
compatibility and credits the upstream [Spicy Lyrics project](https://github.com/Spikerko/spicy-lyrics).

Mappings are cached for 90 days, positive lyric responses for seven days, and
confirmed no-lyrics responses for 24 hours. The SQLite cache is capped at 64 MiB
and never caches authentication, network, rate-limit, or service failures.
