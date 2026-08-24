Karaoke.Integration = function (session) {
  this.session = session;
  this.observer = null;
  this.interval = 0;
  this.wrapper = null;
  this.nativeList = null;
  this.unsubscribe = null;
};

Karaoke.Integration.prototype.start = function () {
  const integration = this;
  this.unsubscribe = this.session.subscribe(function () { integration.sync(); });
  this.observer = new MutationObserver(function () { integration.sync(); });
  this.observer.observe(document.documentElement, { childList: true, subtree: true });
  this.interval = setInterval(function () { integration.sync(); }, 750);
  document.addEventListener("visibilitychange", this._visibility = function () {
    integration.sync();
    integration.session.startRaf();
  });
  this.sync();
};

Karaoke.Integration.prototype.sync = function () {
  const track = Karaoke.readTrack();
  if (track && track.key) this.session.setTrack(track);
  const wrapper = document.querySelector(".nowPlayingView.x4 .lyricsContainer .lyricsWrapper");
  const nativeList = wrapper && wrapper.querySelector("ul.lyricsScroller");
  if (this.wrapper && this.wrapper !== wrapper) {
    this.wrapper.classList.remove("amazify-karaoke-enhanced");
    this.wrapper.removeAttribute("data-amazify-karaoke-status");
  }
  this.wrapper = wrapper;
  this.nativeList = nativeList;
  this.session.setDefaultHost(wrapper);
  if (!wrapper) return;
  wrapper.setAttribute("data-amazify-karaoke-status", this.session.status);
  wrapper.classList.toggle("amazify-karaoke-enhanced", this.session.status === "ready" || this.session.status === "no-lyrics");
  this.session.ensureLoad();
};

Karaoke.Integration.prototype.destroy = function () {
  if (this.observer) this.observer.disconnect();
  clearInterval(this.interval);
  document.removeEventListener("visibilitychange", this._visibility);
  if (this.unsubscribe) this.unsubscribe();
  if (this.wrapper) {
    this.wrapper.classList.remove("amazify-karaoke-enhanced");
    this.wrapper.removeAttribute("data-amazify-karaoke-status");
  }
};
