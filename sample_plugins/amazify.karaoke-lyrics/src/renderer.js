// Reuse native element classes and Vue's scoped-style markers, never its event handlers.
Karaoke.presentationElement = function (template, tag, className) {
  const element = document.createElement(tag);
  element.className = className;
  if (template) Array.from(template.attributes).forEach(function (attribute) {
    if (/^data-v-[a-z0-9]+$/.test(attribute.name)) element.setAttribute(attribute.name, "");
  });
  return element;
};

// A track without Amazon lyrics may never mount the native lyric component.
// Discover its scoped CSS markers, not its font values, so themes still own styling.
Karaoke.lyricScopeTemplate = function (fallback) {
  const template = Karaoke.presentationElement(fallback, "span", "lyricsText");
  let remaining = 50000;
  function inspect(rules, depth) {
    if (!rules || depth > 4) return;
    for (let index = 0; index < rules.length && remaining-- > 0; index += 1) {
      const rule = rules[index];
      const selector = String(rule.selectorText || "");
      if (/\.(lyricsText|lyricsLine|lyricsWrapper)\b/.test(selector)) {
        (selector.match(/data-v-[a-z0-9]+/g) || []).forEach(function (name) { template.setAttribute(name, ""); });
      }
      if (rule.cssRules) inspect(rule.cssRules, depth + 1);
    }
  }
  Array.from(document.styleSheets).forEach(function (sheet) {
    try { inspect(sheet.cssRules, 0); } catch (_error) { /* Cross-origin sheets stay unread. */ }
  });
  return template;
};

Karaoke.Renderer = function (onSeek) {
  this.node = document.createElement("div");
  this.node.className = "amazify-karaoke-host";
  this.node.dataset.amazifyPluginId = "amazify.karaoke-lyrics";
  this.scroller = document.createElement("ul");
  this.scroller.className = "lyricsScroller amazify-karaoke-scroller";
  this.node.appendChild(this.scroller);
  this.container = null;
  this.nativeList = null;
  this.nativeSurfaces = [];
  this.model = null;
  this.lines = [];
  this.activeLines = new Set();
  this.activeLine = -1;
  this.lastTime = null;
  this.manualUntil = 0;
  this.programmaticUntil = 0;
  this.scrollTimer = 0;
  this.resumeTimer = 0;
  this.originalPosition = null;
  this.originalScroll = 0;
  this.scopeTemplate = null;
  this.onSeek = onSeek;
  const renderer = this;
  this.markManual = function () {
    renderer.manualUntil = performance.now() + 4000;
    renderer.node.classList.add("is-manual-scroll");
    clearTimeout(renderer.scrollTimer);
    clearTimeout(renderer.resumeTimer);
    renderer.scrollTimer = setTimeout(function () { renderer.node.classList.remove("is-manual-scroll"); }, 1100);
    renderer.resumeTimer = setTimeout(function () { renderer.centerActive(false); }, 4050);
  };
  ["wheel", "touchstart", "pointerdown", "keydown"].forEach(function (name) {
    renderer.node.addEventListener(name, renderer.markManual, { passive: true });
  });
  this.node.addEventListener("scroll", function () {
    if (performance.now() >= renderer.programmaticUntil) renderer.markManual();
  }, { passive: true });
  this.resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(function () { renderer.measure(); renderer.centerActive(false); }) : null;
  if (this.resizeObserver) this.resizeObserver.observe(this.node);
};

Karaoke.Renderer.prototype.setModel = function (model) {
  if (this.model === model) return;
  this.release();
  this.model = model;
  this.lastTime = null;
  this.manualUntil = 0;
  this.activeLine = -1;
  this.activeLines.clear();
  this.lines = [];
  this.scroller.textContent = "";
  if (!model) { this.release(); return; }
  const renderer = this;
  model.lines.forEach(function (line) {
    const row = Karaoke.presentationElement(null, "li", "lyricsLine amazify-karaoke-line");
    const text = Karaoke.presentationElement(null, "span", "lyricsText");
    row.appendChild(text);
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", line.text);
    text.dir = "auto";
    const tokens = [];
    line.words.forEach(function (word) {
      word.syllables.forEach(function (syllable) {
        const token = document.createElement("span");
        token.className = "amazify-karaoke-token";
        token.textContent = syllable.text;
        text.appendChild(token);
        tokens.push({ node: token, timing: syllable, progress: -1 });
      });
    });
    function seek() {
      renderer.manualUntil = 0;
      clearTimeout(renderer.resumeTimer);
      renderer.onSeek(line.startMs);
      renderer.update(line.startMs, true);
    }
    row.addEventListener("click", seek);
    row.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); seek(); }
    });
    renderer.scroller.appendChild(row);
    renderer.lines.push({ row: row, text: text, tokens: tokens });
  });
};

Karaoke.Renderer.prototype.update = function (timeMs, forceScroll) {
  if (!this.model) return;
  const seek = this.lastTime !== null && (timeMs < this.lastTime - 100 || timeMs - this.lastTime > 1500);
  this.lastTime = timeMs;
  if (seek) this.manualUntil = 0;
  const last = Karaoke.findActiveLine(this.model.lines, timeMs);
  const active = new Set();
  // Overlapping lead/background lines can both be active. DOM writes remain changed-only.
  for (let index = 0; index <= last; index += 1) {
    if (this.model.lines[index].endMs > timeMs) active.add(index);
  }
  const changed = new Set(Array.from(this.activeLines).concat(Array.from(active)));
  const renderer = this;
  changed.forEach(function (index) {
    const line = renderer.lines[index];
    line.row.classList.toggle("current", active.has(index));
    line.tokens.forEach(function (token) {
      const value = Math.round(Karaoke.progress(timeMs, token.timing.startMs, token.timing.endMs) * 1000) / 1000;
      if (value !== token.progress) {
        token.progress = value;
        token.node.style.setProperty("--lyric-progress", String(value * 100) + "%");
      }
    });
  });
  this.activeLines = active;
  if (last !== this.activeLine || forceScroll || seek) {
    this.activeLine = last;
    this.centerActive(Boolean(forceScroll || seek));
  }
};

Karaoke.Renderer.prototype.centerActive = function (force) {
  const target = this.lines[this.activeLine];
  if (!target || !this.node.isConnected || (!force && performance.now() < this.manualUntil)) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  this.programmaticUntil = performance.now() + (reduced ? 100 : 1200);
  const outer = this.node.getBoundingClientRect();
  const inner = target.row.getBoundingClientRect();
  this.node.scrollTo({ top: Math.max(0, this.node.scrollTop + inner.top - outer.top - (this.node.clientHeight - inner.height) / 2), behavior: reduced || force ? "auto" : "smooth" });
};

Karaoke.Renderer.prototype.measure = function () {
  if (!this.node.isConnected || !this.lines.length) return;
  const scroller = this.scroller;
  const height = this.node.clientHeight;
  [[this.lines[0].row, "--karaoke-leading-space", "marginTop"], [this.lines[this.lines.length - 1].row, "--karaoke-trailing-space", "marginBottom"]].forEach(function (item) {
    const value = Math.max(0, (height - item[0].getBoundingClientRect().height) / 2 - (parseFloat(getComputedStyle(item[0])[item[2]]) || 0)).toFixed(2) + "px";
    if (scroller.style.getPropertyValue(item[1]) !== value) scroller.style.setProperty(item[1], value);
  });
};

Karaoke.Renderer.prototype.claim = function (container, presentation) {
  if (!this.model || !container || !container.isConnected) { this.release(); return; }
  const nativeList = Array.from(container.querySelectorAll("ul.lyricsScroller")).find(function (node) { return !node.closest(".amazify-karaoke-host"); });
  // The known wrapper can be empty when only a service has lyrics.
  if (!nativeList && !container.matches(".lyricsWrapper")) { this.release(); return; }
  const changed = container !== this.container || nativeList !== this.nativeList;
  const presentationChanged = this.node.dataset.presentation !== presentation;
  if (changed) {
    this.release();
    this.container = container;
    this.nativeList = nativeList;
    this.originalScroll = container.scrollTop;
    if (getComputedStyle(container).position === "static") {
      this.originalPosition = [container.style.getPropertyValue("position"), container.style.getPropertyPriority("position")];
      container.style.setProperty("position", "relative");
    }
    if (!this.scopeTemplate) this.scopeTemplate = Karaoke.lyricScopeTemplate(container);
    const nativeRow = nativeList && nativeList.querySelector(".lyricsLine") || this.scopeTemplate;
    const nativeText = nativeList && nativeList.querySelector(".lyricsText") || this.scopeTemplate;
    const renderer = this;
    function scope(template, node) {
      Array.from(node.attributes).forEach(function (attr) { if (/^data-v-/.test(attr.name)) node.removeAttribute(attr.name); });
      if (template) Array.from(template.attributes).forEach(function (attr) { if (/^data-v-[a-z0-9]+$/.test(attr.name)) node.setAttribute(attr.name, ""); });
    }
    scope(nativeList || this.scopeTemplate, this.scroller);
    this.lines.forEach(function (line) { scope(nativeRow, line.row); scope(nativeText, line.text); });
    container.appendChild(this.node);
    container.classList.add("amazify-karaoke-enhanced");
    this.nativeSurfaces = Array.from(container.children).filter(function (node) { return node !== renderer.node && (!nativeList || node === nativeList || node.contains(nativeList) || node.matches(".credits")); });
    this.nativeSurfaces.forEach(function (node) { node.setAttribute("data-amazify-karaoke-native", ""); });
    container.scrollTop = 0;
    renderer.measure();
    renderer.update(Karaoke.readPlaybackTime(), true);
  }
  this.node.dataset.presentation = presentation || "normal";
  const inactive = (nativeList || this.scroller).querySelector(".lyricsLine:not(.current) .lyricsText");
  if (inactive) {
    const textColor = getComputedStyle(inactive).color;
    const rowColor = getComputedStyle(inactive.parentNode).color;
    const color = textColor.indexOf("rgba(") === 0 ? textColor : rowColor;
    if (this.scroller.style.getPropertyValue("--karaoke-unsung-color") !== color) this.scroller.style.setProperty("--karaoke-unsung-color", color);
  }
  if (changed || presentationChanged) { this.measure(); this.centerActive(true); }
};

Karaoke.Renderer.prototype.release = function () {
  this.node.remove();
  this.nativeSurfaces.forEach(function (node) { node.removeAttribute("data-amazify-karaoke-native"); });
  this.nativeSurfaces = [];
  if (this.container) {
    this.container.classList.remove("amazify-karaoke-enhanced");
    if (this.originalPosition) {
      if (this.originalPosition[0]) this.container.style.setProperty("position", this.originalPosition[0], this.originalPosition[1]);
      else this.container.style.removeProperty("position");
    }
    this.container.scrollTop = this.originalScroll;
  }
  this.originalPosition = null;
  this.nativeList = null;
  this.container = null;
};

Karaoke.Renderer.prototype.destroy = function () {
  clearTimeout(this.scrollTimer);
  clearTimeout(this.resumeTimer);
  if (this.resizeObserver) this.resizeObserver.disconnect();
  this.release();
  this.model = null;
  this.lines = [];
};
