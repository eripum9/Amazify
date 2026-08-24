Karaoke.number = function (value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
};

Karaoke.timeMs = function (value) {
  const parsed = Karaoke.number(value);
  return parsed > 0 && parsed < 10000 ? parsed * 1000 : parsed;
};

Karaoke.normalizeWords = function (syllables) {
  if (!Array.isArray(syllables)) return [];
  const words = [];
  let current = null;
  syllables.forEach(function (raw) {
    if (!raw || typeof raw !== "object") return;
    const text = String(raw.Text || raw.text || "");
    if (!text) return;
    const token = {
      text: text,
      startMs: Karaoke.timeMs(raw.StartTime != null ? raw.StartTime : raw.startTime),
      endMs: Karaoke.timeMs(raw.EndTime != null ? raw.EndTime : raw.endTime)
    };
    const part = Boolean(raw.IsPartOfWord || raw.isPartOfWord);
    if (part && current) {
      current.text += text;
      current.endMs = Math.max(current.endMs, token.endMs);
      current.syllables.push(token);
    } else {
      current = { text: text, startMs: token.startMs, endMs: token.endMs, syllables: [token] };
      words.push(current);
    }
  });
  return words;
};

Karaoke.normalizeSpicy = function (packed, trackKey) {
  const raw = Karaoke.unpackSLObjPack(packed);
  if (!raw || typeof raw !== "object") return null;
  const type = String(raw.Type || raw.type || "").toLowerCase();
  const content = Array.isArray(raw.Content) ? raw.Content : (Array.isArray(raw.content) ? raw.content : []);
  const lines = [];
  content.forEach(function (entry, lineIndex) {
    if (!entry || typeof entry !== "object") return;
    const lead = entry.Lead || entry.lead || entry;
    const syllables = lead && (lead.Syllables || lead.syllables);
    const words = Karaoke.normalizeWords(syllables);
    let text = String((lead && (lead.Text || lead.text)) || entry.Text || entry.text || "").trim();
    if (!text && words.length) text = words.map(function (word) { return word.text; }).join(" ");
    if (!text) return;
    let startMs = Karaoke.timeMs(lead.StartTime != null ? lead.StartTime : lead.startTime);
    let endMs = Karaoke.timeMs(lead.EndTime != null ? lead.EndTime : lead.endTime);
    if (words.length) {
      startMs = startMs || words[0].startMs;
      endMs = endMs || words[words.length - 1].endMs;
    }
    lines.push({
      id: "spicy-" + lineIndex,
      text: text,
      startMs: startMs,
      endMs: Math.max(startMs, endMs),
      words: words,
      translation: String(entry.Translation || entry.translation || ""),
      background: Boolean(entry.Background || entry.background)
    });
  });
  if (!lines.length) return null;
  let modelType = "line";
  if (type.indexOf("static") >= 0 || !lines.some(function (line) { return line.startMs || line.endMs; })) modelType = "static";
  else if (lines.some(function (line) { return line.words.length && line.words.some(function (word) { return word.endMs > word.startMs; }); })) modelType = "syllable";
  return Object.freeze({
    schemaVersion: 1,
    type: modelType,
    source: "spicy-lyrics",
    trackKey: trackKey,
    language: String(raw.Language || raw.language || ""),
    credits: raw.Credits || raw.credits || null,
    lines: lines
  });
};

Karaoke.normalizeAmazon = function (lyricsData, trackKey) {
  if (!lyricsData || typeof lyricsData !== "object") return null;
  const nested = lyricsData.lyrics && typeof lyricsData.lyrics === "object" ? lyricsData.lyrics : lyricsData;
  let rawLines = nested.lines || nested.Lines || nested.content || [];
  if (!Array.isArray(rawLines) && typeof rawLines === "string") rawLines = rawLines.split(/\r?\n/);
  if (!Array.isArray(rawLines)) return null;
  const lines = [];
  rawLines.forEach(function (raw, index) {
    const item = raw && typeof raw === "object" ? raw : { text: raw };
    const text = String(item.text || item.lyric || item.line || item.words || "").trim();
    if (!text) return;
    const startMs = Karaoke.timeMs(item.startTime != null ? item.startTime : (item.startTimeMs != null ? item.startTimeMs : item.start));
    const endMs = Karaoke.timeMs(item.endTime != null ? item.endTime : (item.endTimeMs != null ? item.endTimeMs : item.end));
    lines.push({ id: "amazon-" + index, text: text, startMs: startMs, endMs: Math.max(startMs, endMs), words: [], translation: "", background: false });
  });
  if (!lines.length) return null;
  for (let index = 0; index < lines.length - 1; index += 1) {
    if (!lines[index].endMs && lines[index + 1].startMs) lines[index].endMs = lines[index + 1].startMs;
  }
  const timed = lines.some(function (line) { return line.startMs > 0 || line.endMs > 0; });
  return Object.freeze({ schemaVersion: 1, type: timed ? "line" : "static", source: "amazon", trackKey: trackKey, language: String(nested.language || ""), credits: nested.credits || null, lines: lines });
};

Karaoke.findActiveLine = function (lines, timeMs) {
  let low = 0;
  let high = lines.length - 1;
  let answer = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (lines[middle].startMs <= timeMs) { answer = middle; low = middle + 1; }
    else high = middle - 1;
  }
  return answer;
};

Karaoke.progress = function (timeMs, startMs, endMs) {
  if (!(endMs > startMs)) return timeMs >= startMs ? 1 : 0;
  return Math.max(0, Math.min(1, (timeMs - startMs) / (endMs - startMs)));
};
