Karaoke.bootstrap = function (Amazify) {
  if (!Amazify.lyricsProvider || Amazify.lyricsProvider.protocolVersion !== 2) throw new Error("Karaoke Lyrics 0.2.3 requires the Amazify 1.1.2 rich-lyrics companion");
  const session = new Karaoke.Session(Amazify.lyricsProvider);
  const integration = new Karaoke.Integration(session);
  const releaseCapability = Amazify.capabilities.provide("amazify.karaoke-lyrics.presentation", {
    version: "1.0.0",
    api: {
      getSnapshot: function () { return session.snapshot(); },
      subscribe: function (listener) { return session.subscribe(listener); },
      claimHost: function (container, options) { return session.claimHost(container, options); }
    }
  });
  const removeSettings = Karaoke.addSettings(Amazify, session);
  const unsubscribeSettings = Amazify.settings.subscribe(function (settings) {
    session.renderer.node.dataset.motion = settings.motion === "on" || settings.motion === "off" ? settings.motion : "system";
  });
  integration.start();
  return function () {
    try { unsubscribeSettings(); removeSettings(); }
    finally { try { releaseCapability(); }
      finally { integration.destroy(); session.destroy(); }
    }
  };
};
