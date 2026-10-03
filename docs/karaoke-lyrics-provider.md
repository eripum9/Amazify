# Karaoke Lyrics

Requires Amazify 1.1.2 or newer. The 0.1.0 Spotify/Spicy Lyrics experiment
remains under `sample_plugins/Scrapped/`; it is not the active implementation.
There is no Spotify login, Premium requirement, OAuth callback, client ID,
Spotify Web API request, or bearer token in the active provider path. Historical
`spotify_auth.py` and its tests remain dormant and are not imported by the app.
The installer build no longer generates a Spotify runtime hook.

## Provider Chain

1. Better Lyrics public `GET https://lyrics-api.boidu.dev/getLyrics`, using
   `s` (title), `a` (artist), `al` (album), and `d` (duration in seconds).
2. Unison public `GET https://unison.boidu.dev/lyrics`, using `song`, `artist`,
   `album`, and `duration` in seconds.
3. Native Amazon lyrics, without an Amazify line-only renderer.

Valid cached rich data is usable offline before network lookup. Otherwise the
network chain tries Better Lyrics first, then Unison. When Better Lyrics supplies
a match score, it must be numeric and at least 80/100; public cached responses
may omit the score. Unison must return matching normalized
title/artist and compatible qualifiers; album and duration are checked when
returned. Matches that are uncertain fail back to native lyrics.

Both services receive track metadata, not Amazon credentials, native lyric
text, artwork, or browser cookies. No API key is sent. Better Lyrics can require
authentication for cache misses; Amazify does not bypass that restriction and
tries Unison instead. These independent services may rate-limit, change or
be unavailable. Availability and track coverage are not promised.

The settings status distinguishes a Better Lyrics public-cache miss from a
service outage and includes Unison's outcome. A public-cache miss is never
stored as a negative result, so a later retry can find newly cached data.
**Retry lyrics lookup** checks again; **Clear lyrics cache** clears local results
and retries for the current open lyrics view.

References: [Better Lyrics response format](https://lyrics-api-docs.boidu.dev/docs/response-format/),
[public access limits](https://lyrics-api-docs.boidu.dev/docs/authentication/),
[Unison API](https://github.com/better-lyrics/unison).

## Presentation Contract

Karaoke owns timing, active words/syllables, seeking and local scrolling only.
It copies native lyric element classes and Vue scoped-style markers, with nested
word spans explicitly inheriting font, weight, size, letter spacing and color.
It does not ship its own palette, fonts or theme-specific typography rules.
Future themes that style native `.lyricsLine` / `.lyricsText` elements inherit
automatically. Themes with direct-child-only selectors may need to account for
the owned host between the wrapper and list.

The `amazify.karaoke-lyrics.presentation` capability stays at v1. True Big Mode
claims its container at priority 100; release returns the same renderer to the
normal view. No refetch or timing reset is needed for presentation changes.
The optional v1 claim field `enabled: false` suspends provider requests and the
renderer for the winning presentation claim. It cancels pending work, rejects
late results and retains already loaded data. Releasing the claim resumes the
normal view. True Big Mode uses this for its **Show lyrics** setting (on by
default), including when Amazon has not created a lyrics wrapper. The setting
does not disable lyrics in other views.

Upcoming rows expose an `is-upcoming` timing class. True Big Mode owns the grey
upcoming-text and unsung-word colors; other themes continue to supply their own
colors. Word/syllable rise and return use eased transitions without changing
font size or weight, and respect the Lyric motion setting.

For provider-only tracks, Karaoke creates a temporary native-styled wrapper in
Amazon's existing lyrics region. True Big Mode uses the enhanced session state
to move artwork from the center to the lyrics layout over two seconds. Removing
the enhancement restores the original placeholder and centered artwork.

Only rich timing mounts the host and hides Amazon's native lyric surface.
Loading, failure, unsupported formats, line-only data, disable and cleanup leave
or restore the original native nodes. Unknown Amazon markup fails soft.

The session retains data while the view is closed and stops its single RAF.
Playback time comes from validated transport state, not a free-running clock.
Track generations discard late results. Manual scroll pauses centering for four
seconds; only manual interaction reveals the scrollbar. Reduced motion disables
smooth centering. Native lyrics remain fully independent of this plugin.

## Parsing And Limits

Providers normalize to schema v1: a rich `syllable` model of timed lines, words
and original syllables. Word-timed spans are represented as single-syllable
words. Timing is never synthesized for line/static lyrics. TTML text is inserted
with `textContent`, never interpreted as HTML, CSS or executable provider code.

The independent parser handles media timestamps, inter-span whitespace, grouped
syllables, speaker metadata and background wrappers. Apple/Composer word and
syllable profiles use media-absolute section timestamps: verse/chorus offsets
are validated as bounds, never added a second time to line or word timestamps.
Apple's namespaced `audio` metadata inside the header is ignored; this mix-offset
description is not a playable audio element. It cannot supply a resource URL or
child elements. Unknown nonzero relative containers, DTD/entities, active
constructs, out-of-range and inconsistent intervals are rejected. Passive
metadata is not rendered.
Limits: 1 MiB XML, depth 32, 10,000 XML nodes, 100,000 text characters, 2,000
lines and 20,000 syllables. Unsupported rich formats are not guessed.

Native network requests allow only the exact HTTPS hosts/paths above, reject
redirects, disable proxies, require JSON and cap response size at 1 MiB. Two
workers and at most eight queued/running loads bound work; load deadlines are
24 seconds with eight-second socket timeouts, inside the renderer's 28-second
timeout. A 429 has at most one retry with a bounded delay. 401/403, 5xx,
malformed data and network errors fall through; 404 is a confirmed miss.

SQLite stores versioned normalized rich responses and metadata fingerprints in
`%APPDATA%/Amazify/lyrics-cache.sqlite3`: seven-day positive TTL, 24-hour confirmed
miss TTL, 64 MiB LRU bound. Auth/network/parser failures are not cached. Old
Spotify mappings are never used. Parser compatibility changes invalidate older
cache entries. Parser/network failures retain their provider-specific reason in
the plugin settings status instead of being reported as missing lyrics.
Clear Cache is in the plugin settings section.

## Motion And Typography

Word wrappers and syllable tokens explicitly inherit the presentation's font,
weight, size, line height and letter spacing, including while highlighted.
Active tokens lift slightly without scaling the glyphs; hovering a line lifts it
and adds a restrained glow. The **Lyric motion** setting offers **Follow system**
(default), **On** and **Off**. On explicitly opts into motion even when Windows
reports reduced motion; Off retains synchronized fill without the movement.

The playback clock interpolates Amazon's coarse position samples for at most
250 ms, resets on seeks and pause changes, and cannot drift through a stalled
player. Only changed classes and progress values are written during playback.
Themes and True Big Mode ignore lyric-only DOM mutations instead of running
their layout synchronization for every highlighted word.

## Development And Verification

Edit the active plugin's `src/` modules, then run
`python scripts/build_karaoke_lyrics.py`. CI checks deterministic output, Node
session/timing regressions, Python provider/parser tests and JavaScript syntax.

`scripts/verify_karaoke_live.py` is an opt-in live Amazon Music test. Stop the
installed daemon first and restart it afterwards. It injects source plugins from
a temporary profile without changing installed plugins. `--lyrics rich` uses
clearly labeled synthetic test data, while `--lyrics live` uses the real broker.
It asserts typography inheritance, a single renderer and native restoration for
missing/error cases. Captures are stored under ignored `build/karaoke-qa/`.
`--native-missing` temporarily simulates missing Amazon lyrics and checks the
provider-only artwork transition. `--lifecycle` exercises real marketplace
toggles, including retaining the same renderer while True Big Mode changes.
`--settings-test` exercises Show lyrics, request suppression and resuming normal
lyrics. `--interactions` seeks, scrolls, reopens the view and advances one real
track, ending paused. Personal plugin settings are restored after testing.
The interaction test requires a multi-track playback queue; lifecycle and
native-fallback comparisons require a current track with Amazon lyrics unless
`--native-missing` is supplied.
`--motion-test` temporarily enables lyric motion, seeks/plays a sung line, and
checks active-token typography, movement, frame intervals, interpolated fill
updates and absence of text rebuilds. `--expect-rich` makes real-provider QA
fail when no enhanced renderer appears.

Runtime state refreshes retain mounted plugins whose manifest and source are
unchanged. Disabling, updating or reinstalling a changed plugin only unmounts
that plugin; capability consumers respond to the affected provider lifecycle.
Unrelated plugin toggles no longer reset lyric timing, hosts or provider loads.

To prepare catalog updates, commit plugin sources first, then run
`python scripts/pin_plugin_catalog.py --source-commit <full-commit> amazify.karaoke-lyrics amazify.true-big-mode`.
This hashes committed Git bytes, avoiding Windows line-ending differences.
Commit the resulting catalog separately. Neither step pushes or publishes.

### Verification Record: 2026-09-06

- Real Amazon client: native, Signal Studio and True Big Mode typography matched
  their original lyric text. Tested 1920x1080, 3440x1390 and compact 960x800.
- Synthetic rich/missing/error responses exercised presentation and lifecycle.
  Fallback lyric-region screenshots were pixel-identical to Karaoke disabled
  in native Amazon, Signal Studio and True Big Mode at 1920x1080.
- Provider-only fixtures verified the two-second artwork movement, cleanup,
  single renderer, Show lyrics suppression, seek, manual scroll, reopening and
  real track switching. Fixtures are not evidence of real provider coverage.
- Separately, a real Unison response for Harvey by Her's passed the native parser
  (37 lines). Better Lyrics returned HTTP 403 here and correctly fell through.
  An end-to-end real-provider playback comparison has not been completed.

### Verification Record: 2026-09-10

- Real Better Lyrics responses for Beat It, Billie Jean and Blinding Lights
  parsed successfully (103, 69 and 37 lines respectively). The previously
  rejected Apple header metadata and absolute section timing were the cause.
- Beat It rendered through the real broker in native Amazon, Signal Studio
  and True Big Mode. Active native text, enhanced text and syllable tokens
  matched in font family, size, weight, style, line height and letter spacing.
- Instrumented sung intervals had one renderer and no text rebuilds. Highlight
  progress updated between the approximately eight-per-second native position
  samples. Frame timings are machine/load dependent, not a performance guarantee.

### Verification Record: 2026-09-11

- Live track switching from an album queue, click-to-seek, manual-scroll
  recentering and reopening passed with Signal Studio and True Big Mode enabled.
- Marketplace disable/enable restored native lyrics and retained a single
  renderer. Show lyrics suppressed provider requests while hidden, reused
  retained data when restored, and resumed normal lyrics after disabling
  True Big Mode.
- Missing and deliberately failed providers left Amazon's native lyric list
  visible with zero Karaoke hosts in native, Signal Studio and True Big Mode.
- At 3440x1390, provider-only lyrics moved the artwork from the exact horizontal
  center to the lyrics layout over two seconds. At 960x800, real Beat It lyrics
  retained matching active-token fonts, one renderer and zero text rebuilds.
- F11 covered the entire Windows monitor and restored the original frame and
  position on exit. True Big Mode auto-entry worked through a real album-art
  click; programmatic clicks are not a substitute for the required user gesture.
