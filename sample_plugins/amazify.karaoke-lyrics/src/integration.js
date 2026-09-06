Karaoke.Integration = function (session) {
  this.session = session; this.timer = 0; this.interval = 0; this.observer = null;
  this.region = null; this.markedView = null; this.addedHasLyrics = false; this.placeholders = [];
};
Karaoke.Integration.prototype.removeRegion = function () {
  this.placeholders.forEach(function (node) { node.removeAttribute("data-amazify-karaoke-placeholder"); });
  this.placeholders = [];
  if (this.region) this.region.remove();
  this.region = null;
};
Karaoke.Integration.prototype.restoreView = function () {
  if (this.markedView) {
    this.markedView.classList.remove("amazify-karaoke-provider-lyrics");
    if (this.addedHasLyrics && !(this.session.track && this.session.track.hasLyrics)) this.markedView.classList.remove("hasLyrics");
  }
  this.markedView = null;
  this.addedHasLyrics = false;
  this.removeRegion();
};
Karaoke.Integration.prototype.hostForView = function (view) {
  const integration = this;
  let wrapper = view && Array.from(view.querySelectorAll(".lyricsContainer .lyricsWrapper")).find(function (node) { return !integration.region || !integration.region.contains(node); });
  const enhance = this.session.model && this.session.presentationEnabled();
  if (!view || !enhance || (this.markedView && this.markedView !== view)) this.restoreView();
  if (!view || !enhance) return wrapper || null;
  if (!this.markedView) {
    this.markedView = view;
    this.addedHasLyrics = !view.classList.contains("hasLyrics");
  }
  view.classList.add("hasLyrics", "amazify-karaoke-provider-lyrics");
  if (wrapper) {
    this.removeRegion();
    return wrapper;
  }
  if (!this.region || !this.region.isConnected) {
    this.removeRegion();
    const template = Karaoke.lyricScopeTemplate(view);
    const outer = view.querySelector(".lyricsContainer");
    const sizeClass = Array.from(view.classList).find(function (name) { return /^x[0-9]+$/.test(name); }) || "x4";
    wrapper = Karaoke.presentationElement(template, "div", "lyricsWrapper " + sizeClass);
    if (outer) {
      this.region = wrapper;
      this.placeholders = Array.from(outer.children);
      this.placeholders.forEach(function (node) { node.setAttribute("data-amazify-karaoke-placeholder", ""); });
      outer.appendChild(wrapper);
    } else {
      this.region = Karaoke.presentationElement(template, "div", "lyricsContainer");
      this.region.appendChild(wrapper);
      view.appendChild(this.region);
    }
    this.region.classList.add("amazify-karaoke-region");
    this.region.dataset.amazifyPluginId = "amazify.karaoke-lyrics";
  }
  return this.region.matches(".lyricsWrapper") ? this.region : this.region.querySelector(".lyricsWrapper");
};
Karaoke.Integration.prototype.start = function () {
  const integration = this;
  this.sync = function () {
    integration.timer = 0;
    const track = Karaoke.readTrack();
    integration.session.setTrack(track && track.title && track.artists.length ? track : null);
    const view = document.querySelector("#transportContainer.nowPlayingShowing .nowPlayingView");
    integration.session.setDefaultHost(integration.hostForView(view), view);
  };
  this.schedule = function (mutations) {
    if (mutations && mutations.every(function (item) { return item.target.closest && item.target.closest(".amazify-karaoke-host"); })) return;
    if (!integration.timer) integration.timer = setTimeout(integration.sync, 0);
  };
  this.observer = new MutationObserver(this.schedule);
  this.observer.observe(document.documentElement, { childList: true, subtree: true });
  this.interval = setInterval(this.sync, 250);
  document.addEventListener("visibilitychange", this.sync);
  this.sync();
};
Karaoke.Integration.prototype.destroy = function () {
  if (this.observer) this.observer.disconnect();
  clearTimeout(this.timer);
  clearInterval(this.interval);
  document.removeEventListener("visibilitychange", this.sync);
  this.restoreView();
};
