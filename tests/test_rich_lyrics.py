from __future__ import annotations

import unittest
from copy import deepcopy

from amazify.rich_lyrics import RichLyricsError, parse_ttml, validate_model


RICH = """<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" xmlns:itunes="http://music.apple.com/lyric-ttml-internal" xmlns:tts="http://www.w3.org/ns/ttml#styling" xml:lang="de">
<head><metadata><ttm:agent type="person" xml:id="v1"/><itunes:originator>fixture</itunes:originator></metadata>
<styling><style xml:id="s1" tts:fontStyle="italic"/></styling></head>
<body><div><p begin="1s" end="3s">
<span begin="1000ms" end="1.25s">Hal</span><span begin="1.25s" end="1.75s">lo </span>
<span begin="00:00:02.000" end="0:02.900">Welt</span>
</p></div></body></tt>"""


class RichLyricsTests(unittest.TestCase):
    def test_parses_rich_timing_and_preserves_xml_spaces(self) -> None:
        model = parse_ttml(RICH, source="better-lyrics", track_key="amazon:key")
        self.assertTrue(validate_model(model))
        line = model["lines"][0]
        self.assertEqual(line["text"], "Hallo Welt")
        self.assertEqual([word["text"] for word in line["words"]], ["Hallo ", "Welt"])
        self.assertEqual(line["words"][0]["syllables"][1]["text"], "lo ")
        self.assertEqual(model["language"], "de")

    def test_rejects_line_only_and_static_text(self) -> None:
        for value in (
            "<tt><body><p begin='1s' end='2s'>static</p></body></tt>",
            "<tt><body><p><span>static</span></p></body></tt>",
            "<tt><body><p>untimed<span begin='1s' end='2s'>timed</span></p></body></tt>",
            "<tt><body><p begin='1s' end='2s'><span begin='1s' end='2s'>whole line</span></p></body></tt>",
        ):
            with self.assertRaises(RichLyricsError):
                parse_ttml(value, source="unison", track_key="key")

    def test_media_time_composer_metadata_and_background_words(self) -> None:
        value = '''<tt xmlns:ttp="http://www.w3.org/ns/ttml#parameter"
            xmlns:c="https://composer.betterlyrics.org/ttml"
            xmlns:ttm="http://www.w3.org/ns/ttml#metadata" ttp:timeBase="media">
            <body><div><p begin="1s" end="3s" c:groupId="g1">
            <span begin="1s" end="2s">One</span> <span begin="2s" end="3s">two</span>
            <span ttm:role="x-bg"><span begin="2s" end="3s">echo</span></span>
            </p></div></body></tt>'''
        model = parse_ttml(value, source="unison", track_key="key")
        self.assertEqual(len(model["lines"]), 2)
        self.assertTrue(model["lines"][1]["background"])
        self.assertEqual(model["lines"][1]["words"][0]["startMs"], 2000)
        with self.assertRaises(RichLyricsError):
            parse_ttml(value.replace('timeBase="media"', 'timeBase="clock"'), source="unison", track_key="key")

    def test_cached_model_rejects_out_of_line_unordered_and_negative_timing(self) -> None:
        valid = parse_ttml(RICH, source="unison", track_key="key")
        for start in (-1, 900, 2500):
            broken = deepcopy(valid)
            broken["lines"][0]["words"][0]["syllables"][0]["startMs"] = start
            self.assertFalse(validate_model(broken))
        with self.assertRaises(RichLyricsError):
            parse_ttml(RICH.replace('end="3s"', 'end="2s"'), source="unison", track_key="key")

    def test_rejects_dtd_entities_styles_and_invalid_times(self) -> None:
        values = (
            "<!DOCTYPE tt [<!ENTITY x 'bad'>]><tt><body/></tt>",
            "<tt><head><style>bad</style></head><body/></tt>",
            "<tt><head><script>bad</script></head><body/></tt>",
            "<tt><body><p><span begin='2s' end='1s'>bad</span></p></body></tt>",
            "<tt><body><p><span begin='nonsense' end='2s'>bad</span></p></body></tt>",
        )
        for value in values:
            with self.assertRaises(RichLyricsError):
                parse_ttml(value, source="unison", track_key="key")

    def test_rejects_oversized_documents_and_unsupported_nested_timing(self) -> None:
        oversized = "<tt><body><p><span begin='1s' end='2s'>" + ("x" * 100_001) + "</span></p></body></tt>"
        nested = "<tt><body><p><span begin='1s' end='2s'><span begin='1s' end='2s'>x</span></span></p></body></tt>"
        for value in (oversized, nested):
            with self.assertRaises(RichLyricsError):
                parse_ttml(value, source="unison", track_key="key")


if __name__ == "__main__":
    unittest.main()
