// The native broker parses provider formats. Validate its rich-only v1 boundary again.
Karaoke.normalizeRich = function (raw, trackKey) {
  if (!raw || raw.schemaVersion !== 1 || raw.type !== "syllable" || raw.trackKey !== trackKey || !Array.isArray(raw.lines) || !raw.lines.length || raw.lines.length > 2000) return null;
  let count = 0;
  let characters = 0;
  function timed(value) {
    if (!value || typeof value.text !== "string" || !Number.isFinite(value.startMs) || !Number.isFinite(value.endMs) || value.startMs < 0 || value.endMs <= value.startMs || value.endMs > 86400000) throw new Error("Invalid rich timing");
    characters += value.text.length;
    if (++count > 30000 || characters > 500000) throw new Error("Rich lyrics exceed limits");
    return { text: value.text, startMs: value.startMs, endMs: value.endMs };
  }
  try {
    const lines = raw.lines.map(function (line) {
      const result = timed(line);
      if (!Array.isArray(line.words) || !line.words.length) throw new Error("Line-only lyrics are not an enhancement");
      let previousEnd = line.startMs;
      result.words = Object.freeze(line.words.map(function (word) {
        const normalized = timed(word);
        const syllables = Array.isArray(word.syllables) && word.syllables.length ? word.syllables : [word];
        normalized.syllables = Object.freeze(syllables.map(function (token) {
          const value = timed(token);
          if (value.startMs < previousEnd || value.endMs > line.endMs) throw new Error("Token outside line or unordered");
          previousEnd = value.endMs;
          return Object.freeze(value);
        }));
        if (normalized.text !== normalized.syllables.map(function (token) { return token.text; }).join("") || normalized.startMs !== normalized.syllables[0].startMs || normalized.endMs !== normalized.syllables[normalized.syllables.length - 1].endMs) throw new Error("Inconsistent word");
        return Object.freeze(normalized);
      }));
      if (result.text !== result.words.map(function (word) { return word.text; }).join("")) throw new Error("Inconsistent line");
      result.background = Boolean(line.background);
      result.agent = String(line.agent || "").slice(0, 100);
      return Object.freeze(result);
    });
    for (let index = 1; index < lines.length; index += 1) {
      if (lines[index].startMs < lines[index - 1].startMs) return null;
    }
    return Object.freeze({ schemaVersion: 1, type: "syllable", source: String(raw.source || ""), trackKey: trackKey, language: String(raw.language || ""), lines: Object.freeze(lines) });
  } catch (_error) { return null; }
};

Karaoke.findActiveLine = function (lines, timeMs) {
  let low = 0, high = lines.length - 1, answer = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (lines[middle].startMs <= timeMs) { answer = middle; low = middle + 1; }
    else high = middle - 1;
  }
  return answer;
};

Karaoke.progress = function (timeMs, startMs, endMs) {
  return endMs > startMs ? Math.max(0, Math.min(1, (timeMs - startMs) / (endMs - startMs))) : 0;
};
