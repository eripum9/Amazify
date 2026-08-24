Karaoke.Renderer = function (onSeek) {
  this.node = document.createElement("div");
  this.node.className = "amazify-karaoke-host";
  this.node.dataset.amazifyPluginId = "amazify.karaoke-lyrics";
  this.node.dataset.presentation = "normal";
  this.scroller = document.createElement("div");
  this.scroller.className = "amazify-karaoke-scroller";
  this.node.appendChild(this.scroller);
  this.model = null;
  this.lineNodes = [];
  this.wordNodes = [];
  this.activeLine = -1;
  this.activeWord = -1;
  this.manualUntil = 0;
  this.programmaticUntil = 0;
  this.scrollTimer = 0;
  this.onSeek = onSeek;
  const renderer = this;
  ["wheel", "touchstart", "pointerdown", "keydown"].forEach(function (name) {
    renderer.scroller.addEventListener(name, function () { renderer.markManual(); }, { passive: true });
  });
  this.scroller.addEventListener("scroll", function () {
    if (performance.now() >= renderer.programmaticUntil) renderer.markManual();
  }, { passive: true });
  this.resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(function () { renderer.centerActive(false); })
    : null;
  if (this.resizeObserver) this.resizeObserver.observe(this.node);
};

Karaoke.Renderer.prototype.markManual = function () {
  this.manualUntil = performance.now() + 4000;
  this.node.classList.add("is-manual-scroll");
  clearTimeout(this.scrollTimer);
  const renderer = this;
  this.scrollTimer = setTimeout(function () { renderer.node.classList.remove("is-manual-scroll"); }, 1100);
};

Karaoke.Renderer.prototype.setModel = function (model) {
  if (this.model === model) return;
  this.model = model;
  this.activeLine = -1;
  this.activeWord = -1;
  while (this.scroller.firstChild) this.scroller.removeChild(this.scroller.firstChild);
  this.lineNodes = [];
  this.wordNodes = [];
  const renderer = this;
  if (!model || !model.lines.length) {
    const empty = document.createElement("div");
    empty.className = "amazify-karaoke-empty";
    empty.textContent = "Lyrics aren't available for this song.";
    this.scroller.appendChild(empty);
    this.node.dataset.ready = "true";
    return;
  }
  model.lines.forEach(function (line, lineIndex) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = "amazify-karaoke-line";
    element.dataset.lineIndex = String(lineIndex);
    element.setAttribute("aria-label", line.text);
    const words = [];
    if (line.words.length && model.type === "syllable") {
      line.words.forEach(function (word, wordIndex) {
        if (wordIndex) element.appendChild(document.createTextNode(" "));
        const token = document.createElement("span");
        token.className = "amazify-karaoke-word";
        token.textContent = word.text;
        token.style.setProperty("--lyric-progress", "0");
        element.appendChild(token);
        words.push(token);
      });
    } else {
      element.textContent = line.text;
    }
    if (line.translation) {
      const translation = document.createElement("small");
      translation.textContent = line.translation;
      element.appendChild(translation);
    }
    element.addEventListener("click", function () {
      renderer.manualUntil = 0;
      renderer.onSeek(line.startMs);
    });
    renderer.scroller.appendChild(element);
    renderer.lineNodes.push(element);
    renderer.wordNodes.push(words);
  });
  this.node.dataset.ready = "true";
};

Karaoke.Renderer.prototype.update = function (timeMs, forceScroll) {
  if (!this.model || this.model.type === "static") return;
  const lineIndex = Karaoke.findActiveLine(this.model.lines, timeMs);
  if (lineIndex !== this.activeLine) {
    if (this.lineNodes[this.activeLine]) this.lineNodes[this.activeLine].classList.remove("is-active");
    this.activeLine = lineIndex;
    this.activeWord = -1;
    if (this.lineNodes[lineIndex]) this.lineNodes[lineIndex].classList.add("is-active");
    this.centerActive(Boolean(forceScroll));
  }
  const line = this.model.lines[lineIndex];
  const nodes = this.wordNodes[lineIndex] || [];
  if (!line || !nodes.length) return;
  let activeWord = -1;
  for (let index = 0; index < line.words.length; index += 1) {
    const word = line.words[index];
    const value = Karaoke.progress(timeMs, word.startMs, word.endMs);
    nodes[index].style.setProperty("--lyric-progress", String(value));
    nodes[index].classList.toggle("is-sung", value >= 1);
    if (value > 0 && value < 1) activeWord = index;
  }
  if (activeWord !== this.activeWord) {
    if (nodes[this.activeWord]) nodes[this.activeWord].classList.remove("is-active");
    this.activeWord = activeWord;
    if (nodes[activeWord]) nodes[activeWord].classList.add("is-active");
  }
};

Karaoke.Renderer.prototype.centerActive = function (force) {
  const target = this.lineNodes[this.activeLine];
  if (!target || (!force && performance.now() < this.manualUntil)) return;
  const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  this.programmaticUntil = performance.now() + (reducedMotion ? 100 : 1200);
  target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
};

Karaoke.Renderer.prototype.claim = function (container, presentation) {
  if (!container) return;
  this.node.dataset.presentation = presentation || "normal";
  if (this.node.parentNode !== container) container.appendChild(this.node);
  this.centerActive(true);
};

Karaoke.Renderer.prototype.destroy = function () {
  clearTimeout(this.scrollTimer);
  if (this.resizeObserver) this.resizeObserver.disconnect();
  this.node.remove();
};
