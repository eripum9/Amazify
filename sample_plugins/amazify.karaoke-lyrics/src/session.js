Karaoke.Session = function (provider) {
  this.provider = provider;
  this.track = null;
  this.model = null;
  this.status = "idle";
  this.providerStatus = null;
  this.generation = 0;
  this.requestKey = "";
  this.listeners = new Set();
  this.claims = new Set();
  this.defaultHost = null;
  this.activeClaim = null;
  this.raf = 0;
  this.renderer = new Karaoke.Renderer(Karaoke.seek);
  this.destroyed = false;
};

Karaoke.Session.prototype.snapshot = function () {
  return Object.freeze({
    track: this.track ? Object.freeze(Object.assign({}, this.track, { amazonLyrics: undefined })) : null,
    status: this.status,
    source: this.model ? this.model.source : "",
    type: this.model ? this.model.type : "",
    hasLyrics: Boolean(this.model && this.model.lines.length),
    providerStatus: this.providerStatus ? Object.freeze(Object.assign({}, this.providerStatus)) : null
  });
};

Karaoke.Session.prototype.publish = function () {
  const snapshot = this.snapshot();
  this.listeners.forEach(function (listener) {
    try { listener(snapshot); } catch (error) { console.warn("[Karaoke Lyrics] listener failed", error); }
  });
};

Karaoke.Session.prototype.subscribe = function (listener) {
  this.listeners.add(listener);
  listener(this.snapshot());
  const session = this;
  return function () { session.listeners.delete(listener); };
};

Karaoke.Session.prototype.setTrack = function (track) {
  if (!track || !track.key || (this.track && this.track.key === track.key)) {
    if (track) this.track = track;
    return;
  }
  if (this.requestKey) this.provider.cancel(this.requestKey).catch(function () {});
  this.generation += 1;
  this.track = track;
  this.model = Karaoke.normalizeAmazon(track.amazonLyrics, track.key);
  this.status = this.model ? "ready" : "idle";
  this.requestKey = "";
  this.renderer.setModel(this.model);
  this.publish();
  this.ensureLoad();
};

Karaoke.Session.prototype.ensureLoad = function () {
  if (!this.track || this.requestKey || !this.visible()) return;
  const generation = this.generation;
  const track = this.track;
  const requestKey = track.key + ":" + generation + ":" + Math.random().toString(36).slice(2);
  this.requestKey = requestKey;
  this.status = this.model ? "ready" : "loading";
  this.publish();
  const session = this;
  this.provider.load(track, requestKey).then(function (result) {
    if (session.destroyed || generation !== session.generation || requestKey !== session.requestKey || !session.track || result.trackKey !== session.track.key) return;
    session.requestKey = "";
    if (result.status === "ready" && result.payload != null) {
      try {
        const upgraded = Karaoke.normalizeSpicy(result.payload, track.key);
        if (upgraded) session.model = upgraded;
      } catch (error) {
        console.warn("[Karaoke Lyrics] provider payload rejected", error);
      }
    }
    session.providerStatus = { status: result.status || "unavailable", detail: result.detail || "", cached: Boolean(result.cached) };
    session.status = session.model ? "ready" : "no-lyrics";
    session.renderer.setModel(session.model);
    session.publish();
    session.syncHost();
    session.startRaf();
  }).catch(function (error) {
    if (generation !== session.generation || requestKey !== session.requestKey) return;
    session.requestKey = "";
    session.providerStatus = { status: "error", detail: String(error && error.message || error) };
    session.status = session.model ? "ready" : "no-lyrics";
    session.renderer.setModel(session.model);
    session.publish();
    session.syncHost();
  });
};

Karaoke.Session.prototype.setDefaultHost = function (container) {
  this.defaultHost = container || null;
  this.syncHost();
  this.ensureLoad();
};

Karaoke.Session.prototype.claimHost = function (container, options) {
  if (!container || !container.nodeType) throw new TypeError("Lyrics host must be a DOM element");
  const claim = {
    container: container,
    presentation: String(options && options.presentation || "normal"),
    priority: Number(options && options.priority || 0),
    order: Date.now() + Math.random(),
    active: true
  };
  this.claims.add(claim);
  this.syncHost();
  this.ensureLoad();
  const session = this;
  return function () {
    if (!claim.active) return;
    claim.active = false;
    session.claims.delete(claim);
    session.syncHost();
  };
};

Karaoke.Session.prototype.syncHost = function () {
  let selected = null;
  this.claims.forEach(function (claim) {
    if (!claim.active || !claim.container.isConnected) return;
    if (!selected || claim.priority > selected.priority || (claim.priority === selected.priority && claim.order > selected.order)) selected = claim;
  });
  this.activeClaim = selected;
  const host = selected ? selected.container : this.defaultHost;
  const presentation = selected ? selected.presentation : "normal";
  if (host && host.isConnected) this.renderer.claim(host, presentation);
  this.startRaf();
};

Karaoke.Session.prototype.visible = function () {
  const node = this.renderer.node;
  if (!node.isConnected || document.visibilityState === "hidden") return false;
  const style = getComputedStyle(node);
  return style.display !== "none" && style.visibility !== "hidden" && node.getClientRects().length > 0;
};

Karaoke.Session.prototype.startRaf = function () {
  if (this.raf || !this.model || this.model.type === "static" || !this.visible()) return;
  const session = this;
  function frame() {
    session.raf = 0;
    if (session.destroyed || !session.model || session.model.type === "static" || !session.visible()) return;
    session.renderer.update(Karaoke.readPlaybackTime(), false);
    if (!Karaoke.isPlaying()) return;
    session.raf = requestAnimationFrame(frame);
  }
  this.raf = requestAnimationFrame(frame);
};

Karaoke.Session.prototype.refreshProviderStatus = function () {
  const session = this;
  return this.provider.status().then(function (status) {
    session.providerStatus = status.spotify || status;
    session.publish();
    return status;
  });
};

Karaoke.Session.prototype.destroy = function () {
  this.destroyed = true;
  if (this.requestKey) this.provider.cancel(this.requestKey).catch(function () {});
  cancelAnimationFrame(this.raf);
  this.raf = 0;
  this.listeners.clear();
  this.claims.clear();
  this.renderer.destroy();
};
