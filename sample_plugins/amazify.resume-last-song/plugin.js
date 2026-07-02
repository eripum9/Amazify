const STORAGE_KEY = "amazify.resume-last-song.state";
const SESSION_ATTEMPT_KEY = "amazify.resume-last-song.attempted";
const SAVE_INTERVAL_MS = 2500;
const AUTO_RESTORE_DELAY_MS = 3600;
const MAX_RESTORE_AGE_MS = 1000 * 60 * 60 * 24 * 30;
const MIN_SEEK_SECONDS = 4;

let saveTimer = null;
let autoRestoreTimer = null;
let saveObserver = null;
let resumeButton = null;
let lastSavedFingerprint = "";
let restoreInProgress = false;
let saveSuspendedUntil = 0;
let userInteracted = false;
let disposed = false;

function getTransport() {
  return (
    document.querySelector("#transport") ||
    document.querySelector('[id*="transport"]') ||
    document.querySelector('[class*="transport"]')
  );
}

function isVisible(element) {
  if (!(element instanceof HTMLElement)) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    Number(style.opacity || "1") > 0
  );
}

function textOf(element) {
  return String(element && element.innerText ? element.innerText : element && element.textContent ? element.textContent : "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\[[^\]]+\]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function parseTime(value) {
  const parts = String(value || "").trim().split(":").map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !Number.isFinite(part))) {
    return null;
  }
  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

function formatSeconds(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "0:00";
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function controlText(value) {
  return /^(play|pause|previous|next|shuffle|repeat|queue|lyrics|devices?|volume|mute|unmute|cast|settings)$/i.test(
    String(value || "").trim()
  );
}

function splitMeaningfulLines(element) {
  const lines = String(element && element.innerText ? element.innerText : "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.filter((line) => {
    if (controlText(line)) {
      return false;
    }
    if (/^-?\d{1,2}:\d{2}(?::\d{2})?$/.test(line)) {
      return false;
    }
    if (line.length > 180) {
      return false;
    }
    return true;
  });
}

function firstVisibleText(root, selectors) {
  for (const selector of selectors) {
    const nodes = Array.from(root.querySelectorAll(selector));
    for (const node of nodes) {
      if (isVisible(node)) {
        const value = textOf(node);
        if (value && !controlText(value) && !/^-?\d{1,2}:\d{2}/.test(value)) {
          return value;
        }
      }
    }
  }
  return "";
}

function readProgress(transport) {
  const slider = Array.from(
    transport.querySelectorAll('input[type="range"], [role="slider"], [aria-valuenow]')
  ).find(isVisible);

  if (slider) {
    const min = Number(slider.getAttribute("min") || 0);
    const max = Number(slider.getAttribute("max") || slider.getAttribute("aria-valuemax") || 0);
    const value = Number(slider.value || slider.getAttribute("aria-valuenow") || 0);
    if (Number.isFinite(max) && max > min && Number.isFinite(value)) {
      const duration = max - min;
      const current = Math.max(0, value - min);
      return {
        current,
        duration,
        fraction: Math.max(0, Math.min(1, current / duration)),
      };
    }
  }

  const text = String(transport.innerText || "");
  const matches = text.match(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g) || [];
  if (matches.length >= 2) {
    const current = parseTime(matches[0]);
    const duration = parseTime(matches[matches.length - 1]);
    if (Number.isFinite(current) && Number.isFinite(duration) && duration > 0) {
      return {
        current,
        duration,
        fraction: Math.max(0, Math.min(1, current / duration)),
      };
    }
  }

  return { current: 0, duration: 0, fraction: 0 };
}

function readArtwork(transport) {
  const image = Array.from(transport.querySelectorAll("img")).find((img) => {
    return isVisible(img) && (img.currentSrc || img.src);
  });
  if (image) {
    return image.currentSrc || image.src;
  }

  const artworkHost = Array.from(transport.querySelectorAll("*")).find((node) => {
    if (!isVisible(node)) {
      return false;
    }
    return /url\(/.test(window.getComputedStyle(node).backgroundImage || "");
  });
  if (!artworkHost) {
    return "";
  }
  const match = window.getComputedStyle(artworkHost).backgroundImage.match(/url\((['"]?)(.*?)\1\)/);
  return match && match[2] ? match[2] : "";
}

function readTrackLink(transport) {
  const link = Array.from(transport.querySelectorAll("a[href]")).find((anchor) => {
    const href = String(anchor.href || "");
    return /\/tracks?\//i.test(href) || /\/albums?\//i.test(href);
  });
  return link ? link.href : "";
}

function readPlayingState(transport) {
  const controls = Array.from(transport.querySelectorAll('button, [role="button"]')).filter(isVisible);
  for (const control of controls) {
    const label = `${control.getAttribute("aria-label") || ""} ${control.getAttribute("title") || ""} ${textOf(control)}`.toLowerCase();
    if (label.includes("pause")) {
      return true;
    }
    if (label.includes("play")) {
      return false;
    }
  }
  return false;
}

function readTrackInfo() {
  const transport = getTransport();
  if (!transport || !isVisible(transport)) {
    return null;
  }

  const title =
    firstVisibleText(transport, [
      '[class*="trackTitle"]',
      '[class*="TrackTitle"]',
      '[class*="songTitle"]',
      '[class*="SongTitle"]',
      '[class*="title"]',
      '[class*="Title"]',
      'a[href*="/tracks/"]',
    ]) || splitMeaningfulLines(transport)[0] || "";

  const lines = splitMeaningfulLines(transport);
  const artist =
    firstVisibleText(transport, [
      '[class*="artistName"]',
      '[class*="ArtistName"]',
      '[class*="subtitle"]',
      '[class*="Subtitle"]',
      '[class*="secondary"]',
      '[class*="Secondary"]',
    ]) || lines.find((line) => normalize(line) !== normalize(title)) || "";

  if (!title || normalize(title).length < 2) {
    return null;
  }

  const progress = readProgress(transport);
  return {
    title,
    artist,
    key: makeTrackKey(title, artist),
    progress,
    artwork: readArtwork(transport),
    link: readTrackLink(transport),
    wasPlaying: readPlayingState(transport),
  };
}

function makeTrackKey(title, artist) {
  return `${normalize(title)}|${normalize(artist)}`;
}

function stateFingerprint(info) {
  const current = Math.floor((info.progress && info.progress.current) || 0);
  const duration = Math.floor((info.progress && info.progress.duration) || 0);
  return `${info.key}|${current}|${duration}|${info.wasPlaying ? "1" : "0"}`;
}

function saveCurrentTrack() {
  if (disposed || restoreInProgress || Date.now() < saveSuspendedUntil) {
    return;
  }
  const info = readTrackInfo();
  if (!info) {
    return;
  }
  const fingerprint = stateFingerprint(info);
  if (fingerprint === lastSavedFingerprint) {
    return;
  }

  const payload = {
    version: 1,
    savedAt: Date.now(),
    title: info.title,
    artist: info.artist,
    key: info.key,
    progress: info.progress,
    artwork: info.artwork,
    link: info.link,
    wasPlaying: info.wasPlaying,
    url: location.href,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  lastSavedFingerprint = fingerprint;
  updateButton(`Saved ${formatSeconds(info.progress.current || 0)}`);
}

function readSavedTrack() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object" || !saved.title || !saved.key) {
      return null;
    }
    if (Date.now() - Number(saved.savedAt || 0) > MAX_RESTORE_AGE_MS) {
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

function getPlayButton(scope) {
  const controls = Array.from((scope || document).querySelectorAll('button, [role="button"]')).filter(isVisible);
  return controls.find((control) => {
    const label = `${control.getAttribute("aria-label") || ""} ${control.getAttribute("title") || ""} ${textOf(control)}`.toLowerCase();
    return label.includes("play") && !label.includes("playlist");
  });
}

function clickElement(element) {
  if (!element) {
    return false;
  }
  element.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, view: window }));
  element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
  element.click();
  element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
  element.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, cancelable: true, view: window }));
  return true;
}

function setNativeRangeValue(input, value) {
  const prototype = Object.getPrototypeOf(input);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  if (descriptor && descriptor.set) {
    descriptor.set.call(input, String(value));
  } else {
    input.value = String(value);
  }
}

function seekToProgressFraction(fraction) {
  const transport = getTransport();
  if (!transport || !Number.isFinite(fraction)) {
    return false;
  }

  const clamped = Math.max(0, Math.min(1, fraction));
  const range = Array.from(transport.querySelectorAll('input[type="range"]')).find(isVisible);
  if (range) {
    const min = Number(range.min || 0);
    const max = Number(range.max || range.getAttribute("aria-valuemax") || 100);
    if (Number.isFinite(max) && max > min) {
      setNativeRangeValue(range, min + (max - min) * clamped);
      range.dispatchEvent(new Event("input", { bubbles: true }));
      range.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }

  const candidates = Array.from(
    transport.querySelectorAll('[role="slider"], [aria-valuenow], [class*="progress"], [class*="Progress"], [class*="scrubber"], [class*="Scrubber"]')
  ).filter((node) => {
    if (!isVisible(node)) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return rect.width >= 80 && rect.height <= 48;
  });
  const target = candidates[0];
  if (!target) {
    return false;
  }

  const rect = target.getBoundingClientRect();
  const clientX = rect.left + rect.width * clamped;
  const clientY = rect.top + rect.height / 2;
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    target.dispatchEvent(
      new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX,
        clientY,
      })
    );
  }
  return true;
}

function sameTrack(current, saved) {
  if (!current || !saved) {
    return false;
  }
  if (current.key === saved.key) {
    return true;
  }
  const currentTitle = normalize(current.title);
  const savedTitle = normalize(saved.title);
  const currentArtist = normalize(current.artist);
  const savedArtist = normalize(saved.artist);
  return Boolean(currentTitle && savedTitle && currentTitle === savedTitle && (!savedArtist || currentArtist.includes(savedArtist) || savedArtist.includes(currentArtist)));
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForTrack(saved, timeoutMs) {
  const start = Date.now();
  while (!disposed && Date.now() - start < timeoutMs) {
    const current = readTrackInfo();
    if (sameTrack(current, saved)) {
      return current;
    }
    await sleep(350);
  }
  return null;
}

function findSearchInput() {
  return Array.from(document.querySelectorAll("input")).find((input) => {
    if (!isVisible(input)) {
      return false;
    }
    const placeholder = String(input.getAttribute("placeholder") || "").toLowerCase();
    const type = String(input.getAttribute("type") || "").toLowerCase();
    const label = String(input.getAttribute("aria-label") || "").toLowerCase();
    return type === "search" || placeholder.includes("search") || placeholder.includes("suche") || label.includes("search");
  });
}

function dispatchTextInput(input, value) {
  input.focus();
  setNativeRangeValue(input, value);
  input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter", code: "Enter" }));
  input.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, cancelable: true, key: "Enter", code: "Enter" }));
}

function scoreSearchCandidate(element, saved) {
  if (!isVisible(element) || element.closest("#transport") || element.closest('[data-amazify-root="true"]')) {
    return 0;
  }
  const text = normalize(textOf(element));
  const title = normalize(saved.title);
  const artist = normalize(saved.artist);
  if (!text || !title || !text.includes(title)) {
    return 0;
  }
  let score = 40;
  if (artist && text.includes(artist)) {
    score += 35;
  }
  if (element.matches('button, [role="button"], a')) {
    score += 10;
  }
  const rect = element.getBoundingClientRect();
  if (rect.top > 90 && rect.top < window.innerHeight - 80) {
    score += 10;
  }
  if (text.length > 260) {
    score -= 20;
  }
  return score;
}

function clickBestSearchResult(saved) {
  const candidates = Array.from(document.querySelectorAll('button, [role="button"], a, [role="row"], [class*="track"], [class*="Track"]'));
  let best = null;
  let bestScore = 0;
  for (const candidate of candidates) {
    const score = scoreSearchCandidate(candidate, saved);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  if (!best) {
    return false;
  }

  const row = best.closest('[role="row"], [class*="track"], [class*="Track"]') || best;
  const rowPlay = getPlayButton(row);
  return clickElement(rowPlay || best);
}

async function searchAndStart(saved) {
  const input = findSearchInput();
  if (!input) {
    updateButton("No search");
    return false;
  }

  dispatchTextInput(input, `${saved.title} ${saved.artist || ""}`.trim());
  updateButton("Searching");
  await sleep(1800);
  if (!clickBestSearchResult(saved)) {
    updateButton("Not found");
    return false;
  }
  return Boolean(await waitForTrack(saved, 9000));
}

async function resumeLoadedTrack(saved) {
  const targetTime = Number(saved.progress && saved.progress.current ? saved.progress.current : 0);
  const duration = Number(saved.progress && saved.progress.duration ? saved.progress.duration : 0);
  if (duration > 0 && targetTime >= MIN_SEEK_SECONDS && targetTime < duration - 3) {
    seekToProgressFraction(targetTime / duration);
    await sleep(500);
  }

  const transport = getTransport();
  if (transport && !readPlayingState(transport)) {
    clickElement(getPlayButton(transport));
  }
  updateButton(`Resumed ${formatSeconds(targetTime)}`);
  saveSuspendedUntil = 0;
  window.setTimeout(saveCurrentTrack, 1000);
}

async function restoreLastTrack(options = {}) {
  if (restoreInProgress || disposed) {
    return;
  }
  const saved = readSavedTrack();
  if (!saved) {
    updateButton("Nothing saved");
    return;
  }

  restoreInProgress = true;
  saveSuspendedUntil = Date.now() + 15000;
  updateButton("Resuming");
  try {
    let current = readTrackInfo();
    if (!sameTrack(current, saved)) {
      current = await waitForTrack(saved, 1800);
    }
    if (!current) {
      current = (await searchAndStart(saved)) ? readTrackInfo() : null;
    }
    if (current) {
      await resumeLoadedTrack(saved);
      sessionStorage.setItem(SESSION_ATTEMPT_KEY, saved.key);
    } else {
      updateButton(options.manual ? "Open manually" : "Resume ready");
    }
  } finally {
    restoreInProgress = false;
    saveSuspendedUntil = 0;
  }
}

function updateButton(status) {
  if (!resumeButton) {
    return;
  }
  const saved = readSavedTrack();
  resumeButton.textContent = "Resume";
  resumeButton.title = saved
    ? `${status || "Resume last song"}: ${saved.title}${saved.artist ? ` - ${saved.artist}` : ""}`
    : status || "No saved song yet";
  resumeButton.setAttribute("aria-label", resumeButton.title);
}

function markUserInteraction(event) {
  if (resumeButton && resumeButton.contains(event.target)) {
    return;
  }
  userInteracted = true;
}

function scheduleAutoRestore() {
  const saved = readSavedTrack();
  if (!saved || sessionStorage.getItem(SESSION_ATTEMPT_KEY) === saved.key) {
    return;
  }
  autoRestoreTimer = window.setTimeout(() => {
    if (!userInteracted) {
      restoreLastTrack({ manual: false });
    }
  }, AUTO_RESTORE_DELAY_MS);
}

resumeButton = Amazify.ui.addHeaderAction(manifest.id, "Resume", () => {
  userInteracted = true;
  restoreLastTrack({ manual: true });
});
resumeButton.title = "Resume last song";
resumeButton.setAttribute("aria-label", "Resume last song");

saveTimer = window.setInterval(saveCurrentTrack, SAVE_INTERVAL_MS);
saveObserver = new MutationObserver(() => {
  window.clearTimeout(saveObserver._amazifyTimer);
  saveObserver._amazifyTimer = window.setTimeout(saveCurrentTrack, 300);
});
saveObserver.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
document.addEventListener("pointerdown", markUserInteraction, true);
document.addEventListener("keydown", markUserInteraction, true);
window.addEventListener("beforeunload", saveCurrentTrack);

saveCurrentTrack();
updateButton("Resume last song");
scheduleAutoRestore();

return () => {
  disposed = true;
  window.clearInterval(saveTimer);
  window.clearTimeout(autoRestoreTimer);
  if (saveObserver) {
    window.clearTimeout(saveObserver._amazifyTimer);
    saveObserver.disconnect();
  }
  document.removeEventListener("pointerdown", markUserInteraction, true);
  document.removeEventListener("keydown", markUserInteraction, true);
  window.removeEventListener("beforeunload", saveCurrentTrack);
  if (resumeButton) {
    resumeButton.remove();
  }
};
