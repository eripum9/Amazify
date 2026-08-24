# Scrapped Plugins

This directory preserves plugin prototypes that are no longer part of Amazify's
active stock catalog. Archived plugins are not discovered by the bundled sample
plugin flow, are not listed in `plugin_catalog.json`, and are not supported or
distributed as current plugins. Their source is retained for research, later
reuse, and historical context.

## Archive Index

| Plugin | Last version | Scrapped | Reason |
|---|---:|---|---|
| [Karaoke Lyrics](amazify.karaoke-lyrics/) | `0.1.0` | 2026-08-24 | Spotify's Web API requires the owner of a development-mode app to maintain Spotify Premium. That makes the Spotify and Spicy Lyrics word/syllable provider unsuitable as a dependable stock feature, while Amazon Music already supplies line-synced lyrics by default. |

## Maintenance

Whenever another plugin is moved here, update the archive index with its name,
last version, archive date, and concrete reason. Archived code must be reviewed
and tested again before it can return to the active catalog; its presence here
does not imply current compatibility or security support.
