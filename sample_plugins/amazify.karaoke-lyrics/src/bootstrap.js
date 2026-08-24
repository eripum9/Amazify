Karaoke.versionAtLeast = function (actual, required) {
  const left = String(actual || "0").split(".").map(Number);
  const right = String(required || "0").split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    if ((left[index] || 0) > (right[index] || 0)) return true;
    if ((left[index] || 0) < (right[index] || 0)) return false;
  }
  return true;
};

Karaoke.cleanLegacyStorage = function () {
  [window.localStorage, window.sessionStorage].forEach(function (storage) {
    try {
      const removals = [];
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key === "amazify.true-big-mode.spotifyAccessToken" || key === "amazify.true-big-mode.spotifyTrackId" || String(key || "").indexOf("amazify.true-big-mode.spotifyTrackId.") === 0) removals.push(key);
      }
      removals.forEach(function (key) { storage.removeItem(key); });
    } catch (_error) {}
  });
};

Karaoke.bootstrap = function (Amazify) {
  if (!Karaoke.versionAtLeast(Amazify.version, "1.1.0")) throw new Error("Karaoke Lyrics requires Amazify 1.1.0 or newer");
  if (!Amazify.lyricsProvider) throw new Error("Karaoke Lyrics provider permission is unavailable");
  Karaoke.cleanLegacyStorage();
  const session = new Karaoke.Session(Amazify.lyricsProvider);
  const integration = new Karaoke.Integration(session);
  integration.start();
  const releaseCapability = Amazify.capabilities.provide("amazify.karaoke-lyrics.presentation", {
    version: "1.0.0",
    api: {
      getSnapshot: function () { return session.snapshot(); },
      subscribe: function (listener) { return session.subscribe(listener); },
      claimHost: function (container, options) { return session.claimHost(container, options); }
    }
  });
  const removeSettings = Karaoke.addSettings(Amazify, session);
  session.refreshProviderStatus().catch(function () {});
  return function () {
    removeSettings();
    releaseCapability();
    integration.destroy();
    session.destroy();
  };
};
