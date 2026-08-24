Karaoke.readTrack = function () {
  const transport = document.querySelector("#transportContainer");
  const vue = transport && transport.__vue__;
  const raw = vue && vue.track && typeof vue.track === "object" ? vue.track : {};
  const progress = vue && vue.playbackProgress && typeof vue.playbackProgress === "object" ? vue.playbackProgress : {};
  const artistsRaw = raw.artists || raw.artist || [];
  const artists = Array.isArray(artistsRaw)
    ? artistsRaw.map(function (item) { return String((item && (item.name || item.artistName)) || item || ""); }).filter(Boolean)
    : [String((artistsRaw && (artistsRaw.name || artistsRaw.artistName)) || artistsRaw || "")].filter(Boolean);
  const title = String(raw.title || raw.name || (transport && transport.querySelector(".trackTitle") && transport.querySelector(".trackTitle").textContent) || "").trim();
  const amazonId = String(raw.asin || raw.id || "").trim();
  let durationMs = Number(raw.duration || raw.durationMs || progress.duration || 0);
  if (durationMs > 0 && durationMs < 10000) durationMs *= 1000;
  const hostname = String(location.hostname || "music.amazon.com").toLowerCase();
  const fingerprint = [title, artists.join(","), raw.album && (raw.album.name || raw.album.title || raw.album), durationMs].join("|").toLowerCase();
  let hash = 2166136261;
  for (let index = 0; index < fingerprint.length; index += 1) {
    hash ^= fingerprint.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const lyricsData = raw.lyricsData && typeof raw.lyricsData === "object" ? raw.lyricsData : null;
  return {
    key: amazonId ? "amazon:" + hostname + ":" + amazonId : "metadata:" + String(hash >>> 0),
    amazonId: amazonId,
    marketplace: hostname,
    title: title,
    artists: artists,
    album: String((raw.album && (raw.album.name || raw.album.title)) || raw.albumName || raw.album || ""),
    durationMs: Math.max(0, Math.round(durationMs || 0)),
    artworkUrl: String(raw.imageUrl || raw.artworkUrl || raw.image || ""),
    explicit: Boolean(raw.explicit || raw.isExplicit),
    isrc: String(raw.isrc || ""),
    hasLyrics: Boolean(raw.hasLyrics || lyricsData),
    amazonLyrics: lyricsData,
    currentTimeMs: Math.max(0, Number(progress.currentTime || 0)),
    playing: String((vue && vue.playerModel && vue.playerModel.state) || "").toLowerCase() === "playing"
  };
};

Karaoke.readPlaybackTime = function () {
  const transport = document.querySelector("#transportContainer");
  const vue = transport && transport.__vue__;
  const value = Number(vue && vue.playbackProgress && vue.playbackProgress.currentTime);
  return Number.isFinite(value) ? Math.max(0, value) : 0;
};

Karaoke.seek = function (timeMs) {
  const transport = document.querySelector("#transportContainer");
  const vue = transport && transport.__vue__;
  const progress = vue && vue.playbackProgress;
  let durationMs = Number(progress && progress.duration) || Number(vue && vue.track && (vue.track.durationMs || vue.track.duration)) || 0;
  if (durationMs > 0 && durationMs < 10000) durationMs *= 1000;
  const slider = transport && transport.querySelector(".slider.progressBar, [class*='progressBar']");
  if (!slider || !durationMs) return false;
  const fraction = Math.max(0, Math.min(1, (Number(timeMs) || 0) / durationMs));
  const rect = slider.getBoundingClientRect();
  if (!rect.width) return false;
  const x = rect.left + rect.width * fraction;
  const y = rect.top + rect.height / 2;
  ["mousedown", "mouseup", "click"].forEach(function (type) {
    slider.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0, buttons: type === "mousedown" ? 1 : 0 }));
  });
  return true;
};
