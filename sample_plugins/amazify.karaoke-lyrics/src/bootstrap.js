Karaoke.bootstrap = function (Amazify) {
  if (!Amazify.lyricsProvider || Amazify.lyricsProvider.protocolVersion !== 2) throw new Error("Karaoke Lyrics 0.2.2 requires the Amazify 1.1.2 rich-lyrics companion");
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
  integration.start();
  return function () {
    try { removeSettings(); }
    finally { try { releaseCapability(); }
      finally { integration.destroy(); session.destroy(); }
    }
  };
};
