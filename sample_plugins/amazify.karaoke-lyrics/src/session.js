Karaoke.Session = function (provider) {
  this.provider = provider;
  this.track = null;
  this.model = null;
  this.status = "idle";
  this.providerStatus = null;
  this.generation = 0;
  this.requestKey = "";
  this.loaded = false;
  this.listeners = new Set();
  this.claims = new Set();
  this.defaultHost = null;
  this.viewHost = null;
  this.activeClaim = null;
  this.claimOrder = 0;
  this.raf = 0;
  this.timeout = 0;
  this.renderer = new Karaoke.Renderer(Karaoke.seek);
  this.destroyed = false;
};

Karaoke.Session.prototype.snapshot = function () {
  return Object.freeze({
    track: this.track ? Object.freeze({ key: this.track.key, hasLyrics: this.track.hasLyrics }) : null,
    status: this.status,
    source: this.model ? this.model.source : "amazon",
    type: this.model ? this.model.type : "",
    enhanced: Boolean(this.model && this.renderer.node.isConnected),
    suspended: !this.presentationEnabled(),
    // v1 compatibility: this means lyrics exist, not that Karaoke owns their renderer.
    hasLyrics: Boolean(this.model || (this.track && this.track.hasLyrics)),
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
Karaoke.Session.prototype.cancel = function () {
  clearTimeout(this.timeout);
  if (this.requestKey) this.provider.cancel(this.requestKey).catch(function () {});
  this.requestKey = "";
};
Karaoke.Session.prototype.setTrack = function (track) {
  if (this.destroyed) return;
  if (track && this.track && this.track.key === track.key) {
    const changed = this.track.hasLyrics !== track.hasLyrics;
    this.track = track;
    if (changed) this.publish();
    return;
  }
  if (!track && !this.track) return;
  this.cancel();
  this.generation += 1;
  this.track = track;
  this.model = null;
  this.loaded = false;
  this.providerStatus = null;
  this.status = track ? "native" : "idle";
  this.stopRaf();
  this.renderer.setModel(null);
  this.publish();
};
Karaoke.Session.prototype.host = function () {
  let selected = null;
  this.claims.forEach(function (claim) {
    if (!claim.container.isConnected) return;
    if (!selected || claim.priority > selected.priority || (claim.priority === selected.priority && claim.order > selected.order)) selected = claim;
  });
  this.activeClaim = selected;
  return selected ? selected.container : this.defaultHost;
};
Karaoke.Session.prototype.visible = function () {
  // Presentations may hide the lyrics region while centering artwork. Visibility
  // of the open view, not that region, controls lazy lookup and avoids a deadlock.
  if (!this.presentationEnabled()) return false;
  const host = this.viewHost || this.host();
  if (!host || !host.isConnected || document.visibilityState === "hidden") return false;
  const style = getComputedStyle(host);
  return style.display !== "none" && style.visibility !== "hidden" && host.getClientRects().length > 0;
};
Karaoke.Session.prototype.presentationEnabled = function () {
  this.host();
  return !this.activeClaim || this.activeClaim.enabled;
};
Karaoke.Session.prototype.ensureLoad = function () {
  if (this.destroyed || !this.track || this.loaded || this.requestKey || !this.visible()) return;
  const session = this;
  const generation = this.generation;
  const track = this.track;
  const requestKey = "karaoke:" + generation + ":" + Math.random().toString(36).slice(2);
  this.requestKey = requestKey;
  this.status = "loading";
  this.publish();
  function current() { return !session.destroyed && generation === session.generation && requestKey === session.requestKey; }
  function finish(result) {
    if (!current()) return;
    clearTimeout(session.timeout);
    session.loaded = true;
    session.requestKey = "";
    session.model = result && result.trackKey === track.key && result.status === "ready" ? Karaoke.normalizeRich(result.payload, track.key) : null;
    session.providerStatus = { status: result && result.status || "unavailable", detail: result && result.detail || "" };
    session.status = session.model ? "ready" : "native";
    session.renderer.setModel(session.model);
    session.syncHost();
    session.publish();
  }
  this.timeout = setTimeout(function () {
    if (!current()) return;
    session.provider.cancel(requestKey).catch(function () {});
    finish({ status: "unavailable", detail: "Provider timed out" });
  }, 28000);
  // Send only matching metadata, never native lyrics, artwork or Amazon account state.
  const query = { key: track.key, title: track.title, artists: track.artists, album: track.album, durationMs: track.durationMs };
  Promise.resolve().then(function () {
    if (!current()) return;
    if (!session.visible()) {
      session.cancel();
      session.status = "native";
      session.publish();
      return;
    }
    return session.provider.load(query, requestKey);
  }).then(finish).catch(function () { finish({ status: "unavailable" }); });
};
Karaoke.Session.prototype.setDefaultHost = function (container, view) {
  this.defaultHost = container || null;
  this.viewHost = view || null;
  this.syncHost();
  this.ensureLoad();
};
Karaoke.Session.prototype.claimHost = function (container, options) {
  if (this.destroyed || !container || container.nodeType !== 1) throw new TypeError("Lyrics host must be a live DOM element");
  const claim = { container: container, presentation: String(options && options.presentation || "normal"), priority: Number(options && options.priority || 0), enabled: !(options && options.enabled === false), order: ++this.claimOrder };
  this.claims.add(claim);
  this.syncHost();
  this.ensureLoad();
  const session = this;
  return function () {
    if (session.claims.delete(claim) && !session.destroyed) {
      session.syncHost();
      session.ensureLoad();
    }
  };
};
Karaoke.Session.prototype.syncHost = function () {
  const wasEnhanced = this.renderer.node.isConnected;
  const host = this.host();
  if (!this.presentationEnabled() && this.requestKey) {
    this.cancel();
    this.status = this.model ? "ready" : (this.track ? "native" : "idle");
    this.publish();
  }
  if (this.model && this.visible()) this.renderer.claim(host, this.activeClaim ? this.activeClaim.presentation : "normal");
  else this.renderer.release();
  if (!this.visible() || !this.renderer.node.isConnected) this.stopRaf();
  else {
    this.renderer.update(Karaoke.readPlaybackTime(), false);
    this.startRaf();
  }
  if (wasEnhanced !== this.renderer.node.isConnected) this.publish();
};
Karaoke.Session.prototype.stopRaf = function () { cancelAnimationFrame(this.raf); this.raf = 0; };
Karaoke.Session.prototype.startRaf = function () {
  if (this.destroyed || this.raf || !this.model || !this.renderer.node.isConnected || !this.visible() || !Karaoke.isPlaying()) return;
  const session = this;
  function frame() {
    session.raf = 0;
    if (session.destroyed || !session.model || !session.visible()) return;
    session.renderer.update(Karaoke.readPlaybackTime(), false);
    if (Karaoke.isPlaying()) session.raf = requestAnimationFrame(frame);
  }
  this.raf = requestAnimationFrame(frame);
};
Karaoke.Session.prototype.destroy = function () {
  this.destroyed = true;
  this.generation += 1;
  this.cancel();
  this.stopRaf();
  this.listeners.clear();
  this.claims.clear();
  this.renderer.destroy();
};
