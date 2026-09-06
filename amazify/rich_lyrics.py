from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast


MAX_XML_BYTES = 1 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 10_000
MAX_TEXT_CHARS = 100_000
MAX_LINES = 2_000
MAX_SYLLABLES = 20_000
MAX_TIME_MS = 24 * 60 * 60 * 1000

_TIME_CLOCK = re.compile(
    r"^(?P<hours>\d{2}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d(?:\.\d{1,3})?)$"
)
_TIME_MINUTES = re.compile(
    r"^(?P<minutes>\d+):(?P<seconds>[0-5]\d(?:\.\d{1,3})?)$"
)
_TIME_OFFSET = re.compile(r"^(?P<value>\d+(?:\.\d{1,6})?)(?P<unit>ms|s)$")
_TIME_SECONDS = re.compile(r"^\d+(?:\.\d{1,6})?$")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_WHITESPACE = re.compile(r"\s")
_SAFE_METADATA_ATTRS = {"timing", "dur", "key", "agent", "songpart", "role", "type", "id", "lang", "lyricoffset"}
_COMPOSER_NS = "{https://composer.betterlyrics.org/ttml}"


class RichLyricsError(ValueError):
    """Raised when a response is not a bounded, rich-synced TTML document."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _parse_time(value: Any) -> int:
    if not isinstance(value, str):
        raise RichLyricsError("TTML timing is not text")
    text = value.strip()
    if not text or len(text) > 64:
        raise RichLyricsError("TTML timing is malformed")
    match = _TIME_CLOCK.fullmatch(text)
    if match:
        seconds = (
            Decimal(match.group("hours")) * 3600
            + Decimal(match.group("minutes")) * 60
            + Decimal(match.group("seconds"))
        )
    else:
        match = _TIME_MINUTES.fullmatch(text)
        if match:
            seconds = Decimal(match.group("minutes")) * 60 + Decimal(match.group("seconds"))
        else:
            match = _TIME_OFFSET.fullmatch(text)
            if match:
                value_decimal = Decimal(match.group("value"))
                seconds = value_decimal / 1000 if match.group("unit") == "ms" else value_decimal
            elif _TIME_SECONDS.fullmatch(text):
                seconds = Decimal(text)
            else:
                raise RichLyricsError("TTML timing is malformed")
    milliseconds = int((seconds * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if not seconds.is_finite() or milliseconds < 0 or milliseconds > MAX_TIME_MS:
        raise RichLyricsError("TTML timing is outside the supported range")
    return milliseconds


def _element_text(element: ET.Element) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(element.text)
    for child in element:
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _language(root: ET.Element, requested: str | None) -> str:
    value = requested or ""
    if not value:
        for element in root.iter():
            candidate = element.attrib.get(_XML_LANG, "")
            if candidate:
                value = candidate
                break
    value = str(value).strip()
    if not value:
        return "und"
    if len(value) > 32 or not re.fullmatch(r"[A-Za-z0-9-]+", value):
        raise RichLyricsError("TTML language is malformed")
    return value


def _validate_tree(root: ET.Element) -> tuple[int, int]:
    node_count = 0
    text_count = 0
    allowed_body = {"tt", "body", "div", "p", "span", "br"}
    active = {"script", "animate", "set", "audio", "video", "iframe", "object", "foreignobject", "canvas"}
    stack: list[tuple[ET.Element, int, bool]] = [(root, 1, False)]
    while stack:
        element, depth, in_head = stack.pop()
        node_count += 1
        if node_count > MAX_NODES or depth > MAX_DEPTH:
            raise RichLyricsError("TTML document is too large")
        name = _local_name(element.tag)
        if name in active:
            raise RichLyricsError("TTML contains an active construct")
        if not in_head and name not in allowed_body and name != "head":
            raise RichLyricsError("TTML contains an unsupported element")
        if not in_head:
            for key, value in element.attrib.items():
                if key in {"begin", "end", _XML_LANG}:
                    continue
                if key == "{http://www.w3.org/ns/ttml#parameter}timeBase" and value == "media":
                    continue
                if key.startswith(_COMPOSER_NS) and _local_name(key) in {"groupid", "instanceidx", "templatelineidx"}:
                    continue
                if _local_name(key) not in _SAFE_METADATA_ATTRS:
                    raise RichLyricsError("TTML contains unsupported styling or timing")
        for text in (element.text, *(child.tail for child in element)):
            if text:
                text_count += len(text)
                if text_count > MAX_TEXT_CHARS:
                    raise RichLyricsError("TTML text is too large")
        child_in_head = in_head or name == "head"
        stack.extend((child, depth + 1, child_in_head) for child in reversed(list(element)))
    return node_count, text_count


def _parse_bounded_xml(raw: bytes) -> ET.Element:
    parser = ET.XMLPullParser(events=("start", "end"))
    depth = 0
    node_count = 0
    root: ET.Element | None = None
    try:
        for offset in range(0, len(raw), 64 * 1024):
            parser.feed(raw[offset : offset + 64 * 1024])
            for event_value in parser.read_events():
                event, element = cast(tuple[str, ET.Element], event_value)
                if event == "start":
                    depth += 1
                    node_count += 1
                    if root is None:
                        root = element
                    if depth > MAX_DEPTH or node_count > MAX_NODES:
                        raise RichLyricsError("TTML document is too large")
                else:
                    depth -= 1
        parser.close()
    except RichLyricsError:
        raise
    except (ET.ParseError, ValueError, UnicodeError) as exc:
        raise RichLyricsError("TTML XML is malformed") from exc
    if root is None or depth != 0:
        raise RichLyricsError("TTML XML is malformed")
    return root


def _timed_spans(line: ET.Element) -> dict[bool, list[tuple[str, int, int]]]:
    result: dict[bool, list[tuple[str, int, int]]] = {False: [], True: []}

    def visit(element: ET.Element, background: bool) -> None:
        name = _local_name(element.tag)
        background = background or any(_local_name(key) == "role" and value == "x-bg" for key, value in element.attrib.items())
        if name == "span":
            begin = element.attrib.get("begin")
            end = element.attrib.get("end")
            timed_children = [child for child in element if _local_name(child.tag) == "span"]
            if begin is None or end is None:
                if begin is not None or end is not None:
                    raise RichLyricsError("TTML span timing is incomplete")
            elif timed_children:
                raise RichLyricsError("Nested timed TTML spans are unsupported")
            else:
                start_ms = _parse_time(begin)
                end_ms = _parse_time(end)
                if end_ms <= start_ms:
                    raise RichLyricsError("TTML syllable timing is invalid")
                text = _element_text(element)
                if not text:
                    raise RichLyricsError("TTML syllable has no text")
                result[background].append((text, start_ms, end_ms))
                return
        for index, child in enumerate(element):
            visit(child, background)
            # Inter-span whitespace is meaningful; do not pretty-print provider XML.
            if index < len(element) - 1 and child.tail and child.tail.isspace() and result[background]:
                text, start, end = result[background][-1]
                if not text[-1:].isspace():
                    result[background][-1] = (text + " ", start, end)

    visit(line, False)
    return result


def _reject_untimed_text(line: ET.Element) -> None:
    for element in line.iter():
        has_timing = _local_name(element.tag) == "span" and "begin" in element.attrib and "end" in element.attrib
        if element.text and not has_timing and element.text.strip():
            raise RichLyricsError("TTML contains untimed lyric text")
        for child in element:
            if child.tail and child.tail.strip():
                raise RichLyricsError("TTML contains untimed lyric text")


def _words(syllables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def finish() -> None:
        if not current:
            return
        words.append(
            {
                "text": "".join(item["text"] for item in current),
                "startMs": current[0]["startMs"],
                "endMs": current[-1]["endMs"],
                "syllables": current.copy(),
            }
        )
        current.clear()

    for syllable in syllables:
        text = syllable["text"]
        if current and _WHITESPACE.match(text):
            finish()
        current.append(syllable)
        if _WHITESPACE.search(text):
            finish()
    finish()
    return words


def parse_ttml(
    value: str,
    *,
    source: str,
    track_key: str,
    language: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, str):
        raise RichLyricsError("TTML payload is not text")
    raw = value.encode("utf-8", "strict")
    if len(raw) > MAX_XML_BYTES:
        raise RichLyricsError("TTML payload is too large")
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper or b"<![" in upper or b"<!" in upper:
        raise RichLyricsError("TTML declarations are not allowed")
    root = _parse_bounded_xml(raw)
    if _local_name(root.tag) != "tt":
        raise RichLyricsError("TTML root is not tt")
    _validate_tree(root)
    if not source or len(source) > 64 or not track_key or len(track_key) > 2048:
        raise RichLyricsError("Lyrics model metadata is invalid")
    lines: list[dict[str, Any]] = []
    syllable_count = 0
    body = next((child for child in root if _local_name(child.tag) == "body"), None)
    if body is None:
        raise RichLyricsError("TTML has no body")
    for element in body.iter():
        if _local_name(element.tag) in {"body", "div"} and "begin" in element.attrib and _parse_time(element.attrib["begin"]) != 0:
            raise RichLyricsError("Relative container timing is unsupported")
        if _local_name(element.tag) != "p":
            continue
        if len(lines) >= MAX_LINES:
            raise RichLyricsError("TTML has too many lines")
        _reject_untimed_text(element)
        groups = _timed_spans(element)
        if not any(groups.values()):
            raise RichLyricsError("TTML contains line-only or static lyrics")
        for background, syllable_values in groups.items():
            if not syllable_values:
                continue
            lines.append(_normalize_line(element, syllable_values, background))
            syllable_count += len(syllable_values)
            if syllable_count > MAX_SYLLABLES:
                raise RichLyricsError("TTML has too many syllables")
    if not lines:
        raise RichLyricsError("TTML contains no rich-synced lines")
    lines.sort(key=lambda line: line["startMs"])
    model = {
        "schemaVersion": 1,
        "type": "syllable",
        "source": source,
        "trackKey": track_key,
        "language": _language(root, language),
        "lines": lines,
    }
    if not validate_model(model):
        raise RichLyricsError("TTML timing is inconsistent")
    return model


def _normalize_line(element: ET.Element, syllable_values: list[tuple[str, int, int]], background: bool) -> dict[str, Any]:
    if len(syllable_values) == 1 and len(syllable_values[0][0].split()) > 1:
        raise RichLyricsError("TTML line has only whole-line timing")
    syllables = [
        {"text": text, "startMs": start_ms, "endMs": end_ms}
        for text, start_ms, end_ms in syllable_values
    ]
    begin = element.attrib.get("begin")
    end = element.attrib.get("end")
    if begin is not None or end is not None:
        if begin is None or end is None:
            raise RichLyricsError("TTML line timing is incomplete")
        line_start = _parse_time(begin)
        line_end = _parse_time(end)
        if line_end <= line_start:
            raise RichLyricsError("TTML line timing is invalid")
    else:
        line_start = min(item["startMs"] for item in syllables)
        line_end = max(item["endMs"] for item in syllables)
    words = _words(syllables)
    if not words or any(not word["text"] for word in words) or not "".join(item["text"] for item in syllables).strip():
        raise RichLyricsError("TTML line has no usable words")
    return {
        "text": "".join(item["text"] for item in syllables),
        "startMs": line_start,
        "endMs": line_end,
        "words": words,
        "background": background,
        "agent": next((value for key, value in element.attrib.items() if _local_name(key) == "agent"), ""),
    }


def validate_model(model: Any) -> bool:
    if not isinstance(model, dict):
        return False
    if model.get("schemaVersion") != 1 or model.get("type") != "syllable":
        return False
    if not isinstance(model.get("source"), str) or not 0 < len(model["source"]) <= 64:
        return False
    if not isinstance(model.get("trackKey"), str) or not 0 < len(model["trackKey"]) <= 2048:
        return False
    if not isinstance(model.get("language"), str) or not re.fullmatch(r"[A-Za-z0-9-]+", model["language"]):
        return False
    if not isinstance(model.get("lines"), list) or not model["lines"] or len(model["lines"]) > MAX_LINES:
        return False
    count = characters = 0
    previous_line = -1
    try:
        for line in model["lines"]:
            if not isinstance(line, dict) or not isinstance(line.get("text"), str):
                return False
            if type(line.get("startMs")) is not int or type(line.get("endMs")) is not int:
                return False
            if not 0 <= line["startMs"] < line["endMs"] <= MAX_TIME_MS or line["startMs"] < previous_line:
                return False
            previous_line = line["startMs"]
            if not isinstance(line.get("words"), list) or not line["words"] or len(line["words"]) > MAX_SYLLABLES:
                return False
            line_text = ""
            previous_token = -1
            for word in line["words"]:
                if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                    return False
                if type(word.get("startMs")) is not int or type(word.get("endMs")) is not int:
                    return False
                if word["endMs"] <= word["startMs"] or not isinstance(word.get("syllables"), list) or not word["syllables"]:
                    return False
                word_text = ""
                for syllable in word["syllables"]:
                    if not isinstance(syllable, dict) or not isinstance(syllable.get("text"), str):
                        return False
                    if type(syllable.get("startMs")) is not int or type(syllable.get("endMs")) is not int:
                        return False
                    if not line["startMs"] <= syllable["startMs"] < syllable["endMs"] <= line["endMs"] or syllable["startMs"] < previous_token:
                        return False
                    previous_token = syllable["endMs"]
                    count += 1
                    characters += len(syllable["text"])
                    if count > MAX_SYLLABLES or characters > MAX_TEXT_CHARS or not syllable["text"]:
                        return False
                    word_text += syllable["text"]
                if word["text"] != word_text or word["startMs"] != word["syllables"][0]["startMs"]:
                    return False
                if word["endMs"] != word["syllables"][-1]["endMs"]:
                    return False
                line_text += word["text"]
            if line["text"] != line_text:
                return False
    except (KeyError, TypeError):
        return False
    return bool(model["lines"])
