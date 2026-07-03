const ROOT_SELECTOR = "#transportContainer.childViewShowing.nowPlayingShowing";
const VIEW_SELECTOR = ".nowPlayingView.x4";
const ART_SELECTOR = ".nowPlayingView .artWrapper.album.large, .nowPlayingView .artWrapper.album, .nowPlayingView .artwork .artWrapper";
const CLOSE_SELECTOR = ".nowPlayingView .closeButtonWrapper";
const TRANSPORT_SELECTOR = "#transport";
const ACTIVE_CLASS = "amazify-true-big-mode-active";
const READY_CLASS = "amazify-true-big-mode-ready";
const HOVER_CLASS = "amazify-true-big-mode-hovered";
const EXIT_PROXY_ATTR = "data-amazify-true-big-mode-exit-proxy";
const OVERLAY_CLASS = "amazify-true-big-mode-exit-overlay";
const DYNAMIC_BG_CLASS = "amazify-true-big-mode-dynamic-bg";
const PROGRESS_CLASS = "amazify-true-big-mode-progress";
const LYRIC_LINE_CLASS = "amazify-true-big-mode-lyric-line";
const LYRIC_ACTIVE_CLASS = "amazify-true-big-mode-lyric-active";
const LETTER_CLASS = "amazify-true-big-mode-letter";
const WORD_CLASS = "amazify-true-big-mode-word";
const WORD_ACTIVE_CLASS = "amazify-true-big-mode-word-active";
const LYRICS_SCROLLING_CLASS = "amazify-true-big-mode-lyrics-scrolling";
const SPICY_LYRICS_API_URL = "https://api.spicylyrics.org";
const SPICY_LYRICS_VERSION = "1.1";
const SPOTIFY_TOKEN_STORAGE_KEY = "amazify.true-big-mode.spotifyAccessToken";
const SPOTIFY_TRACK_ID_STORAGE_KEY = "amazify.true-big-mode.spotifyTrackId";
const SPOTIFY_TRACK_ID_PREFIX = "amazify.true-big-mode.spotifyTrackId:";
const MIN_VISIBLE_ART_SIZE = 80;

let observer = null;
let currentArt = null;
let currentClose = null;
let originalArtAttributes = null;
let dynamicBackground = null;
let progressNode = null;
let lastArtworkUrl = "";
let lastActiveLyric = null;
let stableProgressTrackKey = "";
let stableProgressDuration = 0;
let isProgressSeeking = false;
let previewProgressFraction = null;
let spicyLyricsTrackKey = "";
let spicyLyricsStatus = "idle";
let spicyLyricsData = null;
let lastTimedLyricLine = null;
let syncTimer = null;
let syncFrame = null;
let intervalId = null;
let lyricScrollBindings = new Map();
let fullscreenArmedUntil = 0;
let fullscreenAttempted = false;
let fullscreenEnteredByPlugin = false;

function getBigModeRoot() {
  const root = document.querySelector(ROOT_SELECTOR);
  if (!root || !root.querySelector(VIEW_SELECTOR)) {
    return null;
  }
  return root;
}

function getFullscreenRequest() {
  const element = document.documentElement;
  return (
    element.requestFullscreen ||
    element.webkitRequestFullscreen ||
    element.msRequestFullscreen
  );
}

function getFullscreenExit() {
  return document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
}

function isFullscreenActive() {
  return Boolean(
    document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.msFullscreenElement
  );
}

function isVisibleElement(element) {
  if (!element) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return (
    rect.width >= MIN_VISIBLE_ART_SIZE &&
    rect.height >= MIN_VISIBLE_ART_SIZE &&
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    Number(style.opacity || "1") > 0
  );
}

function findAlbumArt(root) {
  const candidates = Array.from(root.querySelectorAll(ART_SELECTOR));
  return candidates.find(isVisibleElement) || candidates[0] || null;
}

function escapeAttribute(value) {
  return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function cssUrl(value) {
  return `url("${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}")`;
}

function getArtworkUrl(root, art) {
  const image = art ? art.querySelector("img.artImage, img") : null;
  if (image && (image.currentSrc || image.src)) {
    return image.currentSrc || image.src;
  }

  const artwork = art ? art.closest(".artwork") : null;
  const host = artwork || root.querySelector(".background");
  if (host) {
    const raw = window.getComputedStyle(host).getPropertyValue("--artwork").trim();
    const match = raw.match(/url\((['"]?)(.*?)\1\)/);
    if (match && match[2]) {
      return match[2].replace(/\\:/g, ":").replace(/\\\//g, "/");
    }
  }
  return "";
}

function ensureDynamicBackground(root, art) {
  if (!dynamicBackground || !dynamicBackground.isConnected || dynamicBackground.parentElement !== root) {
    if (dynamicBackground) {
      dynamicBackground.remove();
    }
    dynamicBackground = document.createElement("div");
    dynamicBackground.className = DYNAMIC_BG_CLASS;
    dynamicBackground.setAttribute("aria-hidden", "true");
    dynamicBackground.setAttribute("data-amazify-plugin-id", manifest.id);
    root.insertBefore(dynamicBackground, root.firstChild);
  }

  const artworkUrl = getArtworkUrl(root, art);
  if (artworkUrl && artworkUrl !== lastArtworkUrl) {
    lastArtworkUrl = artworkUrl;
    root.style.setProperty("--amazify-true-big-mode-artwork", cssUrl(artworkUrl));
  }
}

function formatSeconds(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "0:00";
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function parseTime(value) {
  const match = String(value || "").trim().match(/^(-)?(\d{1,2}):(\d{2})$/);
  if (!match) {
    return null;
  }
  const seconds = Number(match[2]) * 60 + Number(match[3]);
  return match[1] ? -seconds : seconds;
}

function readProgressFraction(transport) {
  const progress = transport.querySelector(".currentProgress, [class*='currentProgress']");
  if (!progress) {
    return null;
  }
  const rawStyle = progress.getAttribute("style") || "";
  const rawWidth = progress.style ? progress.style.width : "";
  const match = `${rawStyle};${rawWidth}`.match(/(?:width\s*:\s*)?([\d.]+)%/);
  if (!match) {
    return null;
  }
  const fraction = Number(match[1]) / 100;
  if (!Number.isFinite(fraction)) {
    return null;
  }
  return Math.max(0, Math.min(1, fraction));
}

function readProgressTimes(root) {
  const transport = root.querySelector(TRANSPORT_SELECTOR);
  if (!transport) {
    return null;
  }
  const currentNode = transport.querySelector(".currentPlaybackPosition, [class*='currentPlaybackPosition']");
  const remainingNode = transport.querySelector(".currentRemainingPosition, [class*='currentRemainingPosition']");
  let current = parseTime(currentNode ? currentNode.textContent : "");
  const remaining = parseTime(remainingNode ? remainingNode.textContent : "");
  let duration = null;
  const fraction = readProgressFraction(transport);

  if (current !== null && remaining !== null && remaining < 0) {
    duration = current + Math.abs(remaining);
  }

  if (!duration) {
    const times = Array.from(transport.querySelectorAll("*"))
    .map((node) => (node.textContent || "").trim())
    .filter((text) => /^-?\d{1,2}:\d{2}$/.test(text))
    .map(parseTime)
    .filter((value) => value !== null);
    if (times.length >= 2) {
      current = times.find((value) => value >= 0);
      const last = times[times.length - 1];
      duration = last < 0 && current !== null ? current + Math.abs(last) : last;
    }
  }

  if (current === null && duration && fraction !== null) {
    current = duration * fraction;
  }

  if (!duration && fraction === null) {
    return null;
  }
  return {
    current: current || 0,
    duration: duration || 0,
    fraction,
  };
}

function getProgressTrackKey(root) {
  const art = findAlbumArt(root);
  const artworkUrl = getArtworkUrl(root, art) || lastArtworkUrl;
  const track = root.querySelector(`${VIEW_SELECTOR} .track`);
  const trackText = track ? elementText(track) : "";
  return `${artworkUrl}|${trackText}`;
}

function stableDurationForTrack(root, measuredDuration) {
  const trackKey = getProgressTrackKey(root);
  if (trackKey !== stableProgressTrackKey) {
    stableProgressTrackKey = trackKey;
    stableProgressDuration = measuredDuration || 0;
    return stableProgressDuration;
  }

  if (!measuredDuration) {
    return stableProgressDuration;
  }
  if (!stableProgressDuration || Math.abs(measuredDuration - stableProgressDuration) > 2) {
    stableProgressDuration = measuredDuration;
  }
  return stableProgressDuration;
}

function hashString(value) {
  let hash = 0;
  const text = String(value || "");
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) | 0;
  }
  return String(Math.abs(hash));
}

function normalizeLyricText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9' ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function unpackSLObjPack(packed) {
  if (!Array.isArray(packed) || packed.length !== 2 || !Array.isArray(packed[0]) || !Array.isArray(packed[1])) {
    return packed;
  }
  const values = packed[0];
  const stream = packed[1];
  let cursor = 0;

  function read() {
    if (cursor >= stream.length) {
      throw new Error("Packed lyrics ended early");
    }
    return stream[cursor++];
  }

  function pointer(index) {
    if (typeof index !== "number" || index < 0 || index >= values.length) {
      throw new Error("Packed lyrics pointer out of bounds");
    }
    return values[index];
  }

  function readKey() {
    const key = pointer(read());
    if (typeof key !== "string" || key === "__proto__" || key === "constructor" || key === "prototype") {
      throw new Error("Packed lyrics key is unsafe");
    }
    return key;
  }

  function decode(depth) {
    if (depth > 256) {
      throw new Error("Packed lyrics are too deeply nested");
    }
    const op = read();
    if (typeof op !== "number" || !Number.isInteger(op)) {
      throw new Error("Packed lyrics opcode is invalid");
    }
    if (op >= 0) {
      return pointer(op);
    }
    if (op === -1) {
      const count = read();
      const keys = [];
      const obj = {};
      for (let index = 0; index < count; index += 1) {
        keys.push(readKey());
      }
      for (let index = 0; index < count; index += 1) {
        Object.defineProperty(obj, keys[index], {
          value: decode(depth + 1),
          enumerable: true,
          configurable: true,
          writable: true,
        });
      }
      return obj;
    }
    if (op === -2) {
      const count = read();
      const arr = [];
      for (let index = 0; index < count; index += 1) {
        arr.push(decode(depth + 1));
      }
      return arr;
    }
    if (op === -3) {
      const itemCount = read();
      const keyCount = read();
      const keys = [];
      const arr = [];
      for (let index = 0; index < keyCount; index += 1) {
        keys.push(readKey());
      }
      for (let itemIndex = 0; itemIndex < itemCount; itemIndex += 1) {
        const obj = {};
        for (let keyIndex = 0; keyIndex < keyCount; keyIndex += 1) {
          Object.defineProperty(obj, keys[keyIndex], {
            value: decode(depth + 1),
            enumerable: true,
            configurable: true,
            writable: true,
          });
        }
        arr.push(obj);
      }
      return arr;
    }
    if (op === -4) {
      return [];
    }
    if (op === -5) {
      return [decode(depth + 1)];
    }
    if (op === -6) {
      return {};
    }
    throw new Error("Packed lyrics opcode is unknown");
  }

  return decode(0);
}

function getStoredSpotifyToken() {
  try {
    return (
      window.localStorage.getItem(SPOTIFY_TOKEN_STORAGE_KEY) ||
      window.sessionStorage.getItem(SPOTIFY_TOKEN_STORAGE_KEY) ||
      ""
    ).trim();
  } catch (_error) {
    return "";
  }
}

function extractSpotifyTrackIdFromText(value) {
  const text = String(value || "");
  const uriMatch = text.match(/spotify:track:([A-Za-z0-9]{16,32})/);
  if (uriMatch) {
    return uriMatch[1];
  }
  const urlMatch = text.match(/open\.spotify\.com\/track\/([A-Za-z0-9]{16,32})/);
  return urlMatch ? urlMatch[1] : "";
}

function getStoredSpotifyTrackId(trackKey) {
  try {
    return (
      window.localStorage.getItem(`${SPOTIFY_TRACK_ID_PREFIX}${hashString(trackKey)}`) ||
      window.localStorage.getItem(SPOTIFY_TRACK_ID_STORAGE_KEY) ||
      ""
    ).trim();
  } catch (_error) {
    return "";
  }
}

function extractSpotifyTrackId(root, trackKey) {
  const stored = getStoredSpotifyTrackId(trackKey);
  if (stored) {
    return extractSpotifyTrackIdFromText(stored) || stored;
  }
  const candidates = Array.from(
    document.querySelectorAll("[href], [data-uri], [data-track-uri], [data-spotify-id]")
  );
  for (const candidate of candidates) {
    const id = extractSpotifyTrackIdFromText(
      [
        candidate.getAttribute("href"),
        candidate.getAttribute("data-uri"),
        candidate.getAttribute("data-track-uri"),
        candidate.getAttribute("data-spotify-id"),
      ].join(" ")
    );
    if (id) {
      return id;
    }
  }
  return extractSpotifyTrackIdFromText(root.innerHTML.slice(0, 50000));
}

function syllableLineText(syllables) {
  let text = "";
  syllables.forEach((syllable, index) => {
    if (index > 0 && !syllable.IsPartOfWord) {
      text += " ";
    }
    text += syllable.Text || "";
  });
  return text;
}

function normalizeSpicyLyrics(rawLyrics) {
  if (!rawLyrics || !Array.isArray(rawLyrics.Content)) {
    return null;
  }
  const lines = [];
  rawLyrics.Content.forEach((content) => {
    const lead = content && content.Lead;
    const syllables = lead && Array.isArray(lead.Syllables) ? lead.Syllables : [];
    if (!syllables.length) {
      return;
    }
    lines.push({
      text: syllableLineText(syllables),
      normalizedText: normalizeLyricText(syllableLineText(syllables)),
      startTime: Number(lead.StartTime || syllables[0].StartTime || 0),
      endTime: Number(lead.EndTime || syllables[syllables.length - 1].EndTime || 0),
      syllables,
    });
  });
  return lines.length ? { type: rawLyrics.Type, lines } : null;
}

function fetchSpicyLyricsIfPossible(root) {
  const trackKey = getProgressTrackKey(root);
  if (trackKey !== spicyLyricsTrackKey) {
    spicyLyricsTrackKey = trackKey;
    spicyLyricsStatus = "idle";
    spicyLyricsData = null;
    lastTimedLyricLine = null;
  }
  if (spicyLyricsStatus !== "idle") {
    return;
  }

  const token = getStoredSpotifyToken();
  const spotifyTrackId = extractSpotifyTrackId(root, trackKey);
  if (!token || !spotifyTrackId) {
    spicyLyricsStatus = "unavailable";
    return;
  }

  spicyLyricsStatus = "loading";
  fetch(`${SPICY_LYRICS_API_URL}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "SpicyLyrics-Version": SPICY_LYRICS_VERSION,
      "SpicyLyrics-WebAuth": `Bearer ${token}`,
    },
    body: JSON.stringify({
      queries: [
        {
          operation: "lyrics",
          variables: {
            id: spotifyTrackId,
            auth: "SpicyLyrics-WebAuth",
          },
        },
      ],
      client: {
        version: SPICY_LYRICS_VERSION,
      },
    }),
  })
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
    .then((payload) => {
      const query = payload && payload.queries && payload.queries[0] && payload.queries[0].result;
      if (!query || query.httpStatus !== 200 || !query.data) {
        throw new Error("No timed lyrics returned");
      }
      spicyLyricsData = normalizeSpicyLyrics(unpackSLObjPack(query.data));
      spicyLyricsStatus = spicyLyricsData ? "ready" : "unavailable";
    })
    .catch(() => {
      spicyLyricsStatus = "unavailable";
      spicyLyricsData = null;
    });
}

function findTimedLyricLine(text) {
  if (!spicyLyricsData || !Array.isArray(spicyLyricsData.lines)) {
    return null;
  }
  const normalized = normalizeLyricText(text);
  if (!normalized) {
    return null;
  }
  return (
    spicyLyricsData.lines.find((line) => line.normalizedText === normalized) ||
    spicyLyricsData.lines.find((line) => line.normalizedText.includes(normalized) || normalized.includes(line.normalizedText)) ||
    null
  );
}

function progressFractionFromEvent(event) {
  if (!progressNode) {
    return null;
  }
  const rail = progressNode.querySelector(".amazify-true-big-mode-progress-rail");
  if (!rail) {
    return null;
  }
  const point = event.touches && event.touches.length ? event.touches[0] : event;
  const rect = rail.getBoundingClientRect();
  if (!rect.width) {
    return null;
  }
  return Math.max(0, Math.min(1, (point.clientX - rect.left) / rect.width));
}

function dispatchSeekMouseEvent(target, type, x, y, buttons) {
  target.dispatchEvent(
    new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
      buttons,
    })
  );
}

function seekToProgressFraction(fraction) {
  const root = getBigModeRoot();
  if (!root) {
    return;
  }
  const transport = root.querySelector(TRANSPORT_SELECTOR);
  const progressBar = transport
    ? transport.querySelector(".slider.progressBar, [class*='progressBar']")
    : null;
  if (!progressBar) {
    return;
  }

  const rect = progressBar.getBoundingClientRect();
  if (!rect.width) {
    return;
  }
  const x = rect.left + rect.width * Math.max(0, Math.min(1, fraction));
  const y = rect.top + rect.height / 2;
  dispatchSeekMouseEvent(progressBar, "mousemove", x, y, 0);
  dispatchSeekMouseEvent(progressBar, "mousedown", x, y, 1);
  dispatchSeekMouseEvent(document, "mousemove", x, y, 1);
  dispatchSeekMouseEvent(document, "mouseup", x, y, 0);
  dispatchSeekMouseEvent(progressBar, "click", x, y, 0);
}

function setProgressPreview(fraction) {
  previewProgressFraction = Math.max(0, Math.min(1, fraction));
  if (progressNode) {
    progressNode.style.setProperty("--amazify-progress", `${previewProgressFraction * 100}%`);
  }
}

function seekFromProgressEvent(event, commit) {
  const fraction = progressFractionFromEvent(event);
  if (fraction === null) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  setProgressPreview(fraction);
  if (commit) {
    seekToProgressFraction(fraction);
    previewProgressFraction = null;
  }
}

function stopProgressSeeking(event) {
  if (!isProgressSeeking) {
    return;
  }
  isProgressSeeking = false;
  if (event) {
    seekFromProgressEvent(event, true);
  }
  document.removeEventListener("mousemove", onProgressDragMove, true);
  document.removeEventListener("mouseup", stopProgressSeeking, true);
  document.removeEventListener("touchmove", onProgressDragMove, true);
  document.removeEventListener("touchend", stopProgressSeeking, true);
}

function onProgressDragMove(event) {
  if (isProgressSeeking) {
    seekFromProgressEvent(event, false);
  }
}

function onProgressMouseDown(event) {
  isProgressSeeking = true;
  seekFromProgressEvent(event, false);
  document.addEventListener("mousemove", onProgressDragMove, true);
  document.addEventListener("mouseup", stopProgressSeeking, true);
}

function onProgressClick(event) {
  if (!isProgressSeeking) {
    seekFromProgressEvent(event, true);
  }
}

function onProgressTouchStart(event) {
  isProgressSeeking = true;
  seekFromProgressEvent(event, false);
  document.addEventListener("touchmove", onProgressDragMove, true);
  document.addEventListener("touchend", stopProgressSeeking, true);
}

function onProgressKeydown(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
    return;
  }
  const root = getBigModeRoot();
  if (!root) {
    return;
  }
  const times = readProgressTimes(root);
  if (!times) {
    return;
  }
  const duration = stableDurationForTrack(root, times.duration);
  const currentFraction =
    times.fraction !== null
      ? times.fraction
      : duration
        ? Math.max(0, Math.min(1, times.current / duration))
        : 0;
  const nextFraction =
    currentFraction + (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 0.1 : 0.025);
  event.preventDefault();
  seekToProgressFraction(Math.max(0, Math.min(1, nextFraction)));
}

function ensureProgress(root, art) {
  const track = art ? art.closest(".track") : null;
  if (!track) {
    if (progressNode) {
      progressNode.remove();
      progressNode = null;
    }
    return;
  }

  if (!progressNode || !progressNode.isConnected) {
    progressNode = document.createElement("div");
    progressNode.className = PROGRESS_CLASS;
    progressNode.setAttribute("role", "slider");
    progressNode.setAttribute("tabindex", "0");
    progressNode.setAttribute("aria-label", "Seek song");
    progressNode.setAttribute("aria-valuemin", "0");
    progressNode.setAttribute("data-amazify-plugin-id", manifest.id);
    progressNode.innerHTML = `
      <span class="amazify-true-big-mode-progress-current">0:00</span>
      <span class="amazify-true-big-mode-progress-rail"><span class="amazify-true-big-mode-progress-fill"></span></span>
      <span class="amazify-true-big-mode-progress-duration">0:00</span>
    `;
    progressNode.addEventListener("mousedown", onProgressMouseDown, true);
    progressNode.addEventListener("touchstart", onProgressTouchStart, true);
    progressNode.addEventListener("click", onProgressClick, true);
    progressNode.addEventListener("keydown", onProgressKeydown, true);
  }

  const artwork = art.closest(".artwork") || art;
  if (progressNode.parentElement !== track) {
    artwork.insertAdjacentElement("afterend", progressNode);
  }
}

function syncProgress(root) {
  if (!progressNode || !progressNode.isConnected) {
    return;
  }
  const times = readProgressTimes(root);
  if (!times || (!times.duration && times.fraction === null)) {
    progressNode.hidden = true;
    return;
  }
  progressNode.hidden = false;
  const duration = stableDurationForTrack(root, times.duration);
  const current = times.current || (duration && times.fraction !== null ? duration * times.fraction : 0);
  const fraction =
    previewProgressFraction !== null
      ? previewProgressFraction
      : times.fraction !== null
      ? times.fraction
      : Math.max(0, Math.min(1, current / duration));
  progressNode.querySelector(".amazify-true-big-mode-progress-current").textContent =
    formatSeconds(current);
  progressNode.querySelector(".amazify-true-big-mode-progress-duration").textContent =
    duration ? formatSeconds(duration) : "";
  progressNode.setAttribute("aria-valuemax", String(Math.round(duration || 0)));
  progressNode.setAttribute("aria-valuenow", String(Math.round(current || 0)));
  progressNode.style.setProperty("--amazify-progress", `${fraction * 100}%`);
}

function requestFullscreenOnce() {
  if (fullscreenAttempted || isFullscreenActive() || Date.now() > fullscreenArmedUntil) {
    return;
  }
  const request = getFullscreenRequest();
  if (typeof request !== "function") {
    fullscreenAttempted = true;
    return;
  }

  fullscreenAttempted = true;
  try {
    Promise.resolve(request.call(document.documentElement))
      .then(() => {
        fullscreenEnteredByPlugin = isFullscreenActive();
      })
      .catch(() => {
        fullscreenEnteredByPlugin = false;
      });
  } catch (_error) {
    fullscreenEnteredByPlugin = false;
  }
}

function maybeArmFullscreen(event) {
  if (getBigModeRoot()) {
    return;
  }
  const target = event.target instanceof Element ? event.target : null;
  const transport = document.querySelector("#transportContainer");
  if (!target || !transport || !transport.contains(target)) {
    return;
  }
  if (!target.closest(".artWrapper, .artwork, .artImage")) {
    return;
  }
  fullscreenArmedUntil = Date.now() + 3000;
}

function exitPluginFullscreen() {
  if (!fullscreenEnteredByPlugin || !isFullscreenActive()) {
    fullscreenEnteredByPlugin = false;
    return;
  }
  const exit = getFullscreenExit();
  fullscreenEnteredByPlugin = false;
  if (typeof exit === "function") {
    try {
      Promise.resolve(exit.call(document)).catch(() => {});
    } catch (_error) {
      // Ignore browser-specific fullscreen teardown failures.
    }
  }
}

function rememberArtAttributes(art) {
  originalArtAttributes = {
    ariaLabel: art.getAttribute("aria-label"),
    role: art.getAttribute("role"),
    tabindex: art.getAttribute("tabindex"),
    title: art.getAttribute("title"),
  };
}

function restoreAttribute(element, name, value) {
  if (value === null) {
    element.removeAttribute(name);
    return;
  }
  element.setAttribute(name, value);
}

function ensureOverlay(art) {
  let overlay = Array.from(art.children).find((child) =>
    child.classList.contains(OVERLAY_CLASS)
  );
  if (overlay && overlay.querySelector(".amazify-true-big-mode-hover-controls")) {
    return overlay;
  }
  if (overlay) {
    overlay.remove();
  }

  overlay = document.createElement("div");
  overlay.className = OVERLAY_CLASS;
  overlay.setAttribute("aria-hidden", "true");
  overlay.setAttribute("data-amazify-plugin-id", manifest.id);
  overlay.innerHTML = `
    <div class="amazify-true-big-mode-exit-affordance">
      <svg class="amazify-true-big-mode-exit-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M6.7 5.3 12 10.6l5.3-5.3L18.7 6.7 13.4 12l5.3 5.3-1.4 1.4L12 13.4l-5.3 5.3-1.4-1.4 5.3-5.3-5.3-5.3 1.4-1.4Z"></path>
      </svg>
    </div>
    <div class="amazify-true-big-mode-hover-controls">
      ${controlButtonMarkup("shuffle", "Shuffle", '<path d="M16.8 3.7h3.7v3.7h-1.8V6.6l-3.1 3.1-1.3-1.3 3.1-3.1h-.6V3.7ZM4 7.1h3.1c1.3 0 2.5.5 3.4 1.4l.8.8-1.3 1.3-.8-.8c-.6-.6-1.3-.9-2.1-.9H4V7.1Zm12.8 9.5h.6l-3.1-3.1 1.3-1.3 3.1 3.1v-.8h1.8v3.7h-3.7v-1.6ZM4 15.1h3.1c.8 0 1.6-.3 2.1-.9l7.2-7.2 1.3 1.3-7.2 7.2c-.9.9-2.1 1.4-3.4 1.4H4v-1.8Z"></path>')}
      ${controlButtonMarkup("previous", "Previous", '<path d="M6 5h2v14H6V5Zm3 7 10 7V5L9 12Z"></path>')}
      ${controlButtonMarkup("playpause", "Play or pause", '<path data-amazify-play-icon d="M8 5v14l11-7L8 5Z"></path><path data-amazify-pause-icon d="M7 5h4v14H7V5Zm6 0h4v14h-4V5Z"></path>')}
      ${controlButtonMarkup("next", "Next", '<path d="M16 5h2v14h-2V5ZM5 19l10-7L5 5v14Z"></path>')}
      ${controlButtonMarkup("repeat", "Repeat", '<path d="M7 6h8.7l-1.8-1.8L15.2 3 19 6.8l-3.8 3.8-1.3-1.2 1.8-1.8H7c-1.7 0-3 1.3-3 3H2c0-2.8 2.2-5 5-5Zm10 7.4h2c0 2.8-2.2 5-5 5H5.3l1.8 1.8L5.8 21 2 17.2l3.8-3.8 1.3 1.2-1.8 1.8H14c1.7 0 3-1.3 3-3Z"></path>')}
    </div>
  `;
  overlay.querySelectorAll("[data-amazify-control]").forEach((button) => {
    button.addEventListener("click", onHoverControlClick, true);
  });
  art.appendChild(overlay);
  return overlay;
}

function controlButtonMarkup(action, label, paths) {
  const repeatBadge =
    action === "repeat"
      ? '<span class="amazify-true-big-mode-repeat-one-badge" aria-hidden="true">1</span>'
      : "";
  return `
    <button
      class="amazify-true-big-mode-hover-control"
      type="button"
      data-amazify-control="${escapeAttribute(action)}"
      aria-label="${escapeAttribute(label)}"
      title="${escapeAttribute(label)}"
    >
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths}</svg>
      ${repeatBadge}
    </button>
  `;
}

function controlKeywords(action) {
  return {
    shuffle: ["shuffle"],
    previous: ["previous", "prev", "back"],
    playpause: ["pause", "play"],
    next: ["next"],
    repeat: ["repeat"],
  }[action] || [];
}

function controlClassSelectors(action) {
  return {
    shuffle: ["[data-qaid='shuffle']", ".shuffleButton", ".shuffle"],
    previous: ["[data-qaid='previous']", ".prevButton", ".previousButton", ".previous"],
    playpause: ["[data-qaid='playPause']", ".playPause", ".playButton", ".pauseButton", ".playPauseButton", ".playbackButton"],
    next: ["[data-qaid='next']", ".nextButton", ".next"],
    repeat: ["[data-qaid='repeat']", ".repeatButton", ".repeat"],
  }[action] || [];
}

function clickableAncestor(element) {
  if (!element) {
    return null;
  }
  return element.closest("button, [role='button'], .button") || element;
}

function findTransportControl(action) {
  const transport = document.querySelector(TRANSPORT_SELECTOR);
  if (!transport) {
    return null;
  }

  for (const selector of controlClassSelectors(action)) {
    const direct = transport.querySelector(selector);
    const clickable = clickableAncestor(direct);
    if (clickable && !clickable.closest(`.${OVERLAY_CLASS}`)) {
      return clickable;
    }
  }

  const keywords = controlKeywords(action);
  const candidates = Array.from(
    transport.querySelectorAll("button, [role='button'], .button, [aria-label], [title], svg")
  );
  for (const candidate of candidates) {
    const haystack = [
      candidate.getAttribute("aria-label"),
      candidate.getAttribute("title"),
      candidate.getAttribute("data-original-title"),
      candidate.className,
      candidate.textContent,
    ]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    if (!keywords.some((keyword) => haystack.includes(keyword))) {
      continue;
    }
    const clickable = clickableAncestor(candidate);
    if (clickable && !clickable.closest(`.${OVERLAY_CLASS}`)) {
      return clickable;
    }
  }
  return null;
}

function onHoverControlClick(event) {
  const button = event.currentTarget;
  const action = button ? button.getAttribute("data-amazify-control") : "";
  event.preventDefault();
  event.stopPropagation();
  if (!action) {
    return;
  }
  const control = findTransportControl(action);
  if (control) {
    control.click();
  }
}

function looksActiveControl(control) {
  if (!control) {
    return false;
  }
  if (readsAsPressed(control)) {
    return true;
  }
  const text = controlStateText(control);
  return (
    text.includes("selected") ||
    text.includes("active") ||
    text.includes("disable") ||
    text.includes("turn off")
  );
}

function readsAsPressed(control) {
  if (!control) {
    return false;
  }
  const ariaPressed = String(control.getAttribute("aria-pressed") || "").toLowerCase();
  const ariaChecked = String(control.getAttribute("aria-checked") || "").toLowerCase();
  const ariaSelected = String(control.getAttribute("aria-selected") || "").toLowerCase();
  return ariaPressed === "true" || ariaChecked === "true" || ariaSelected === "true";
}

function valueText(value) {
  if (!value) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object" && "baseVal" in value) {
    return String(value.baseVal || "");
  }
  return String(value);
}

function elementStateText(element) {
  if (!element) {
    return "";
  }
  return [
    element.getAttribute("aria-label"),
    element.getAttribute("title"),
    element.getAttribute("data-original-title"),
    element.getAttribute("data-qaid"),
    element.getAttribute("data-testid"),
    element.getAttribute("aria-pressed"),
    element.getAttribute("aria-checked"),
    element.getAttribute("aria-selected"),
    element.getAttribute("aria-current"),
    element.getAttribute("class"),
    valueText(element.className),
    element.textContent,
  ]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
}

function controlStateText(control) {
  if (!control) {
    return "";
  }
  const parts = [elementStateText(control)];
  control
    .querySelectorAll("[aria-label], [title], [data-original-title], [aria-pressed], [aria-checked], [aria-selected], [aria-current], [class], svg use")
    .forEach((element) => {
      parts.push(elementStateText(element));
      if (typeof SVGUseElement !== "undefined" && element instanceof SVGUseElement) {
        parts.push(String(element.getAttribute("href") || element.getAttribute("xlink:href") || "").toLowerCase());
      }
    });
  return parts.join(" ");
}

function parseRgbColor(value) {
  const parts = String(value || "").match(/\d+(\.\d+)?/g);
  if (!parts || parts.length < 3) {
    return null;
  }
  return parts.slice(0, 3).map(Number);
}

function colorLooksActive(value) {
  const rgb = parseRgbColor(value);
  if (!rgb) {
    return false;
  }
  const [r, g, b] = rgb;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max < 120 || max - min < 44) {
    return false;
  }
  return (g > r + 28 && g > 130) || (b > r + 28 && b > 130);
}

function computedControlLooksActive(control) {
  if (!control) {
    return false;
  }
  const elements = [
    control,
    ...Array.from(control.querySelectorAll("svg, path, use, [class*='icon'], [class*='Icon']")),
  ];
  return elements.some((element) => {
    const style = window.getComputedStyle(element);
    return colorLooksActive(style.color) || colorLooksActive(style.fill) || colorLooksActive(style.stroke);
  });
}

function isExplicitControlOff(text, keyword) {
  return (
    text.includes(`${keyword} off`) ||
    text.includes(`${keyword} is off`) ||
    text.includes(`${keyword}: off`) ||
    text.includes(`${keyword} disabled`) ||
    text.includes(`enable ${keyword}`) ||
    text.includes(`turn ${keyword} on`) ||
    text.includes(`turn on ${keyword}`)
  );
}

function shuffleState(control) {
  if (!control) {
    return "unavailable";
  }
  const text = controlStateText(control);
  if (isExplicitControlOff(text, "shuffle")) {
    return "off";
  }
  if (
    readsAsPressed(control) ||
    text.includes("shuffle on") ||
    text.includes("shuffle is on") ||
    text.includes("shuffle: on") ||
    text.includes("shuffle enabled") ||
    text.includes("disable shuffle") ||
    text.includes("turn shuffle off") ||
    text.includes("turn off shuffle") ||
    text.includes("shuffle active") ||
    computedControlLooksActive(control)
  ) {
    return "on";
  }
  return looksActiveControl(control) ? "on" : "off";
}

function repeatState(control) {
  if (!control) {
    return "unavailable";
  }
  const text = controlStateText(control);
  const repeatOneText =
    text.includes("repeat one") ||
    text.includes("repeat 1") ||
    text.includes("repeat1") ||
    text.includes("repeat-one") ||
    text.includes("repeat_one") ||
    text.includes("repeat this song") ||
    text.includes("repeat current song") ||
    text.includes("repeat current track") ||
    text.includes("repeat single") ||
    text.includes("repeat_single");
  const repeatOneIsNextAction =
    text.includes("turn repeat one on") ||
    text.includes("turn on repeat one") ||
    text.includes("enable repeat one");
  if (
    repeatOneText &&
    (!repeatOneIsNextAction || readsAsPressed(control) || text.includes("active") || text.includes("selected"))
  ) {
    return "one";
  }
  if (isExplicitControlOff(text, "repeat")) {
    return "off";
  }
  if (
    readsAsPressed(control) ||
    text.includes("repeat all") ||
    text.includes("repeat on") ||
    text.includes("repeat is on") ||
    text.includes("repeat: on") ||
    text.includes("repeat enabled") ||
    text.includes("disable repeat") ||
    text.includes("turn repeat off") ||
    text.includes("turn off repeat") ||
    text.includes("repeat active") ||
    computedControlLooksActive(control)
  ) {
    return "all";
  }
  return looksActiveControl(control) ? "all" : "off";
}

function isPauseState(control) {
  if (!control) {
    return false;
  }
  const text = [
    control.getAttribute("aria-label"),
    control.getAttribute("title"),
    control.getAttribute("data-original-title"),
    control.className,
    control.innerHTML,
  ]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
  if (text.includes("svg-icon--pause") || text.includes("#pause")) {
    return true;
  }
  if (text.includes("svg-icon--play") || text.includes("#play")) {
    return false;
  }
  return text.includes("pause");
}

function syncHoverControls() {
  if (!currentArt || !currentArt.isConnected) {
    return;
  }
  currentArt.querySelectorAll("[data-amazify-control]").forEach((button) => {
    const action = button.getAttribute("data-amazify-control");
    const source = findTransportControl(action);
    button.disabled = !source;
    let isActive = looksActiveControl(source);
    if (action === "shuffle") {
      const state = shuffleState(source);
      isActive = state === "on";
      button.dataset.shuffleState = state;
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      button.setAttribute("title", isActive ? "Shuffle on" : "Shuffle off");
      button.setAttribute("aria-label", isActive ? "Shuffle on" : "Shuffle off");
    } else {
      delete button.dataset.shuffleState;
      button.removeAttribute("aria-pressed");
    }
    if (action === "repeat") {
      const state = repeatState(source);
      isActive = state === "all" || state === "one";
      button.dataset.repeatMode = state;
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      const label = state === "one" ? "Repeat one" : state === "all" ? "Repeat all" : "Repeat off";
      button.setAttribute("title", label);
      button.setAttribute("aria-label", label);
    } else {
      delete button.dataset.repeatMode;
    }
    button.classList.toggle("amazify-true-big-mode-control-active", isActive);
    if (action === "playpause") {
      button.dataset.playbackState = isPauseState(source) ? "pause" : "play";
    }
  });
}

function onAlbumArtClick(event) {
  if (event.target instanceof Element && event.target.closest("[data-amazify-control]")) {
    return;
  }
  const root = getBigModeRoot();
  const close = root ? root.querySelector(CLOSE_SELECTOR) : currentClose;
  if (!root || !close) {
    return;
  }

  event.preventDefault();
  event.stopPropagation();
  close.click();
}

function onAlbumArtKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  onAlbumArtClick(event);
}

function showAlbumArtHover() {
  if (currentArt) {
    currentArt.classList.add(HOVER_CLASS);
  }
}

function hideAlbumArtHover() {
  if (currentArt) {
    currentArt.classList.remove(HOVER_CLASS);
  }
}

function showAlbumArtHoverFromEvent() {
  showAlbumArtHover();
}

function hideAlbumArtHoverFromEvent(event) {
  const related = event && event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (currentArt && related && currentArt.contains(related)) {
    return;
  }
  hideAlbumArtHover();
}

function bindAlbumArt(art, close) {
  if (currentArt === art && currentClose === close) {
    ensureOverlay(art);
    return;
  }

  unbindAlbumArt();
  currentArt = art;
  currentClose = close;
  rememberArtAttributes(art);

  art.classList.add("amazify-true-big-mode-album-exit");
  art.setAttribute(EXIT_PROXY_ATTR, "true");
  art.setAttribute("aria-label", "Exit Big Mode");
  art.setAttribute("role", "button");
  art.setAttribute("tabindex", "0");
  art.removeAttribute("title");
  ensureOverlay(art);

  art.addEventListener("click", onAlbumArtClick, true);
  art.addEventListener("keydown", onAlbumArtKeydown, true);
  art.addEventListener("mouseenter", showAlbumArtHover, true);
  art.addEventListener("mouseleave", hideAlbumArtHover, true);
  art.addEventListener("pointerenter", showAlbumArtHoverFromEvent, true);
  art.addEventListener("pointerleave", hideAlbumArtHoverFromEvent, true);
  art.addEventListener("mouseover", showAlbumArtHoverFromEvent, true);
  art.addEventListener("mouseout", hideAlbumArtHoverFromEvent, true);
  art.addEventListener("focus", showAlbumArtHover, true);
  art.addEventListener("blur", hideAlbumArtHover, true);
}

function unbindAlbumArt() {
  if (!currentArt) {
    currentClose = null;
    originalArtAttributes = null;
    return;
  }

  currentArt.removeEventListener("click", onAlbumArtClick, true);
  currentArt.removeEventListener("keydown", onAlbumArtKeydown, true);
  currentArt.removeEventListener("mouseenter", showAlbumArtHover, true);
  currentArt.removeEventListener("mouseleave", hideAlbumArtHover, true);
  currentArt.removeEventListener("pointerenter", showAlbumArtHoverFromEvent, true);
  currentArt.removeEventListener("pointerleave", hideAlbumArtHoverFromEvent, true);
  currentArt.removeEventListener("mouseover", showAlbumArtHoverFromEvent, true);
  currentArt.removeEventListener("mouseout", hideAlbumArtHoverFromEvent, true);
  currentArt.removeEventListener("focus", showAlbumArtHover, true);
  currentArt.removeEventListener("blur", hideAlbumArtHover, true);
  currentArt.classList.remove("amazify-true-big-mode-album-exit");
  currentArt.classList.remove(HOVER_CLASS);
  currentArt.removeAttribute(EXIT_PROXY_ATTR);
  currentArt.querySelectorAll(`:scope > .${OVERLAY_CLASS}`).forEach((overlay) => overlay.remove());

  if (originalArtAttributes) {
    restoreAttribute(currentArt, "aria-label", originalArtAttributes.ariaLabel);
    restoreAttribute(currentArt, "role", originalArtAttributes.role);
    restoreAttribute(currentArt, "tabindex", originalArtAttributes.tabindex);
    restoreAttribute(currentArt, "title", originalArtAttributes.title);
  }

  currentArt = null;
  currentClose = null;
  originalArtAttributes = null;
}

function elementText(element) {
  return String(element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
}

function isInsideTrackChrome(element) {
  return Boolean(
    element.closest(
      ".track, .artwork, .closeButtonWrapper, #transport, .amazify-true-big-mode-exit-overlay"
    )
  );
}

function isLikelyLyricLine(element) {
  if (!(element instanceof HTMLElement) || isInsideTrackChrome(element)) {
    return false;
  }
  const text = elementText(element);
  if (text.length < 2 || text.length > 220) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  if (
    rect.width < 120 ||
    rect.height < 18 ||
    rect.x < window.innerWidth * 0.32 ||
    rect.bottom < 0 ||
    rect.top > window.innerHeight
  ) {
    return false;
  }
  const childTextBlocks = Array.from(element.children).filter((child) => {
    const childRect = child.getBoundingClientRect();
    return childRect.height > 14 && elementText(child).length > 0;
  });
  const className = String(element.className || "").toLowerCase();
  const parentClassName = String(element.parentElement ? element.parentElement.className : "").toLowerCase();
  const isLyricsText =
    className.includes("lyricstext") ||
    className.includes("lyrics-text") ||
    className.includes("lyric-text");
  if (!isLyricsText && childTextBlocks.length > 0) {
    return false;
  }
  if (
    className.includes("lyricscontainer") ||
    className.includes("lyricswrapper") ||
    className.includes("lyricsscroller")
  ) {
    return false;
  }
  return (
    isLyricsText ||
    parentClassName.includes("lyric") ||
    parentClassName.includes("lyrics")
  );
}

function findAmazonCurrentLyricLine(view, lines) {
  const selectors = [
    ".lyricsLine.current .lyricsText",
    ".lyricsLine.current [class*='lyricsText']",
    "[class*='lyricsLine'][class*='current'] [class*='lyricsText']",
    "[class*='current'] .lyricsText",
  ];
  for (const selector of selectors) {
    const candidate = view.querySelector(selector);
    if (!candidate) {
      continue;
    }
    if (lines.indexOf(candidate) !== -1) {
      return candidate;
    }
    const child = Array.from(candidate.querySelectorAll(".lyricsText, [class*='lyricsText']")).find(
      (node) => lines.indexOf(node) !== -1
    );
    if (child) {
      return child;
    }
  }
  return null;
}

function lyricActiveScore(element) {
  const className = String(element.className || "").toLowerCase();
  const style = window.getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > window.innerHeight) {
    return -Infinity;
  }
  let score = 0;
  if (/(active|current|selected|highlight|playing|focused)/.test(className)) {
    score += 100;
  }
  if (Number.parseFloat(style.opacity || "1") >= 0.82) {
    score += 12;
  }
  if (Number.parseInt(style.fontWeight, 10) >= 700) {
    score += 16;
  }
  const colorMatch = style.color.match(/\d+(\.\d+)?/g);
  if (colorMatch) {
    const [r, g, b] = colorMatch.map(Number);
    if ((r + g + b) / 3 > 170) {
      score += 15;
    }
  }
  const centerDistance = Math.abs(rect.top + rect.height / 2 - window.innerHeight / 2);
  score += Math.max(0, 32 - centerDistance / 12);
  return score;
}

function renderTimedLyricLine(element, timedLine, currentSeconds) {
  const text = elementText(element);
  if (!timedLine || !Array.isArray(timedLine.syllables)) {
    return false;
  }
  const renderKey = `${timedLine.normalizedText}|${timedLine.syllables.length}`;
  if (element.dataset.amazifyTimedLyricKey !== renderKey) {
    element.dataset.amazifyLyricText = text;
    element.dataset.amazifyTimedLyricKey = renderKey;
    element.textContent = "";
    timedLine.syllables.forEach((syllable, index) => {
      if (index > 0 && !syllable.IsPartOfWord) {
        element.appendChild(document.createTextNode(" "));
      }
      const span = document.createElement("span");
      span.className = WORD_CLASS;
      span.textContent = syllable.Text || "";
      span.setAttribute("data-amazify-word-start", String(Number(syllable.StartTime || 0)));
      span.setAttribute("data-amazify-word-end", String(Number(syllable.EndTime || 0)));
      element.appendChild(span);
    });
  }

  const currentMs = currentSeconds * 1000;
  element.querySelectorAll(`.${WORD_CLASS}`).forEach((word) => {
    const start = Number(word.getAttribute("data-amazify-word-start") || "0");
    word.classList.toggle(WORD_ACTIVE_CLASS, currentMs >= start);
  });
  return true;
}

function unwrapLyricEnhancements(element) {
  if (element.hasAttribute("data-amazify-lyric-text")) {
    element.textContent = element.getAttribute("data-amazify-lyric-text") || "";
    element.removeAttribute("data-amazify-lyric-text");
  }
  element.removeAttribute("data-amazify-timed-lyric-key");
  element.style.removeProperty("--amazify-letter-count");
}

function restoreLyricElement(element) {
  unwrapLyricEnhancements(element);
  element.classList.remove(LYRIC_LINE_CLASS, LYRIC_ACTIVE_CLASS);
}

function restoreLyricEnhancements() {
  document.querySelectorAll(
    `[data-amazify-lyric-text], [data-amazify-timed-lyric-key], .${LYRIC_LINE_CLASS}, .${LYRIC_ACTIVE_CLASS}`
  ).forEach(restoreLyricElement);
  lastActiveLyric = null;
}

function isLikelyLyricScroller(element) {
  if (!(element instanceof HTMLElement) || isInsideTrackChrome(element)) {
    return false;
  }
  const className = String(element.className || "").toLowerCase();
  if (
    !className.includes("lyricscontainer") &&
    !className.includes("lyricswrapper") &&
    !className.includes("lyricsscroller")
  ) {
    return false;
  }
  return element.scrollHeight > element.clientHeight + 8;
}

function showLyricScrollbarTemporarily(element) {
  const binding = lyricScrollBindings.get(element);
  if (!binding) {
    return;
  }
  element.classList.add(LYRICS_SCROLLING_CLASS);
  if (binding.timer !== null) {
    window.clearTimeout(binding.timer);
  }
  binding.timer = window.setTimeout(() => {
    binding.timer = null;
    element.classList.remove(LYRICS_SCROLLING_CLASS);
  }, 900);
}

function bindLyricScrollbar(element) {
  if (lyricScrollBindings.has(element)) {
    return;
  }
  const binding = {
    timer: null,
    onScroll: () => showLyricScrollbarTemporarily(element),
  };
  lyricScrollBindings.set(element, binding);
  element.addEventListener("scroll", binding.onScroll, { passive: true });
}

function cleanupLyricScrollbars(root = null) {
  for (const [element, binding] of lyricScrollBindings) {
    if (root && element.isConnected && root.contains(element)) {
      continue;
    }
    element.removeEventListener("scroll", binding.onScroll);
    element.classList.remove(LYRICS_SCROLLING_CLASS);
    if (binding.timer !== null) {
      window.clearTimeout(binding.timer);
    }
    lyricScrollBindings.delete(element);
  }
}

function syncLyricScrollbars(root) {
  if (!root) {
    cleanupLyricScrollbars();
    return;
  }
  cleanupLyricScrollbars(root);
  root
    .querySelectorAll(".lyricsContainer, .lyricsWrapper, .lyricsScroller, [class*='lyricsContainer'], [class*='lyricsWrapper'], [class*='lyricsScroller'], [class*='LyricsContainer'], [class*='LyricsWrapper'], [class*='LyricsScroller']")
    .forEach((element) => {
      if (isLikelyLyricScroller(element)) {
        bindLyricScrollbar(element);
      }
    });
}

function enhanceLyrics(root) {
  const view = root.querySelector(VIEW_SELECTOR);
  if (!view) {
    return;
  }
  fetchSpicyLyricsIfPossible(root);
  const lines = Array.from(view.querySelectorAll(".lyricsText, [class*='lyricsText']")).filter(isLikelyLyricLine);
  const enhancedLines = Array.from(
    view.querySelectorAll(
      `.${LYRIC_LINE_CLASS}, .${LYRIC_ACTIVE_CLASS}, [data-amazify-lyric-text], [data-amazify-timed-lyric-key]`
    )
  );
  enhancedLines.forEach((line) => {
    if (lines.indexOf(line) === -1) {
      restoreLyricElement(line);
    }
  });
  if (!lines.length) {
    lastActiveLyric = null;
    return;
  }

  let activeLine = findAmazonCurrentLyricLine(view, lines);
  let activeScore = -Infinity;
  const progress = readProgressTimes(root);
  const currentSeconds = progress ? progress.current : 0;
  lines.forEach((line) => {
    line.classList.add(LYRIC_LINE_CLASS);
    if (activeLine) {
      return;
    }
    const score = lyricActiveScore(line);
    if (score > activeScore) {
      activeLine = line;
      activeScore = score;
    }
  });

  lines.forEach((line) => {
    const isActive = line === activeLine;
    if (isActive) {
      const timedLine = findTimedLyricLine(elementText(line));
      if (!renderTimedLyricLine(line, timedLine, currentSeconds)) {
        unwrapLyricEnhancements(line);
      }
      if (lastActiveLyric !== line) {
        line.classList.remove(LYRIC_ACTIVE_CLASS);
        void line.offsetWidth;
      }
      line.classList.add(LYRIC_ACTIVE_CLASS);
    } else {
      unwrapLyricEnhancements(line);
      line.classList.remove(LYRIC_ACTIVE_CLASS);
    }
  });
  lastActiveLyric = activeLine;
}

function syncPolishedBigMode(root, art) {
  ensureDynamicBackground(root, art);
  ensureProgress(root, art);
  syncProgress(root);
  syncHoverControls();
  syncLyricScrollbars(root);
  enhanceLyrics(root);
}

function syncFastBigModeState() {
  const root = getBigModeRoot();
  if (!root) {
    syncBigMode();
    return;
  }
  syncProgress(root);
  syncHoverControls();
  syncLyricScrollbars(root);
  enhanceLyrics(root);
}

function restorePolishedBigMode() {
  stopProgressSeeking();
  if (dynamicBackground) {
    dynamicBackground.remove();
    dynamicBackground = null;
  }
  if (progressNode) {
    progressNode.remove();
    progressNode = null;
  }
  lastArtworkUrl = "";
  lastActiveLyric = null;
  stableProgressTrackKey = "";
  stableProgressDuration = 0;
  previewProgressFraction = null;
  spicyLyricsTrackKey = "";
  spicyLyricsStatus = "idle";
  spicyLyricsData = null;
  lastTimedLyricLine = null;
  cleanupLyricScrollbars();
  restoreLyricEnhancements();
}

function syncBigMode() {
  const root = getBigModeRoot();
  if (!root) {
    document.body.classList.remove(ACTIVE_CLASS, READY_CLASS);
    unbindAlbumArt();
    restorePolishedBigMode();
    fullscreenAttempted = false;
    fullscreenArmedUntil = 0;
    exitPluginFullscreen();
    return;
  }

  const art = findAlbumArt(root);
  const close = root.querySelector(CLOSE_SELECTOR);
  document.body.classList.add(ACTIVE_CLASS);

  if (art) {
    if (close) {
      bindAlbumArt(art, close);
      document.body.classList.add(READY_CLASS);
    } else {
      document.body.classList.remove(READY_CLASS);
      unbindAlbumArt();
    }
    syncPolishedBigMode(root, art);
  } else {
    document.body.classList.remove(READY_CLASS);
    unbindAlbumArt();
  }

  requestFullscreenOnce();
}

function scheduleSync() {
  if (syncTimer !== null) {
    return;
  }
  syncTimer = window.setTimeout(() => {
    syncTimer = null;
    if (syncFrame !== null) {
      return;
    }
    syncFrame = window.requestAnimationFrame(() => {
      syncFrame = null;
      syncBigMode();
    });
  }, 120);
}

observer = new MutationObserver(scheduleSync);
observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
});
intervalId = window.setInterval(syncFastBigModeState, 350);
document.addEventListener("click", maybeArmFullscreen, true);
syncBigMode();

return () => {
  if (observer) {
    observer.disconnect();
  }
  if (syncTimer !== null) {
    window.clearTimeout(syncTimer);
  }
  if (syncFrame !== null) {
    window.cancelAnimationFrame(syncFrame);
  }
  if (intervalId !== null) {
    window.clearInterval(intervalId);
  }
  document.removeEventListener("click", maybeArmFullscreen, true);
  document.body.classList.remove(ACTIVE_CLASS, READY_CLASS);
  unbindAlbumArt();
  restorePolishedBigMode();
  exitPluginFullscreen();
};
