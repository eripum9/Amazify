Karaoke.addSettings = function (Amazify, session) {
  return Amazify.ui.addSettingsSection({
    id: "provider",
    title: "Karaoke Lyrics",
    render: function (host) {
      host.className = "amazify-karaoke-settings";
      const status = document.createElement("div");
      status.className = "amazify-setting-row amazify-karaoke-provider-status";
      const actions = document.createElement("div");
      actions.className = "amazify-karaoke-settings-actions";
      host.appendChild(status);
      host.appendChild(actions);
      let alive = true;
      function button(label, handler) {
        const element = document.createElement("button");
        element.type = "button";
        element.textContent = label;
        element.addEventListener("click", handler);
        actions.appendChild(element);
      }
      function render(providerStatus) {
        if (!alive) return;
        const spotify = providerStatus && providerStatus.spotify ? providerStatus.spotify : providerStatus;
        const state = spotify && spotify.state || "checking";
        status.textContent = "Spotify beta: " + state + (spotify && spotify.detail ? " - " + spotify.detail : "");
        while (actions.firstChild) actions.removeChild(actions.firstChild);
        if (state === "connected") {
          button("Reconnect", function () { Amazify.lyricsProvider.beginAuth().then(refresh); });
          button("Disconnect", function () { Amazify.lyricsProvider.disconnect().then(refresh); });
        } else {
          button("Connect Spotify", function () { Amazify.lyricsProvider.beginAuth().then(refresh); });
        }
        button("Clear lyrics cache", function () { Amazify.lyricsProvider.clearCache().then(refresh); });
      }
      function refresh() {
        return Amazify.lyricsProvider.status().then(function (value) { render(value); return value; }).catch(function (error) { render({ state: "error", detail: String(error.message || error) }); });
      }
      refresh();
      const timer = setInterval(refresh, 3000);
      return function () { alive = false; clearInterval(timer); };
    }
  });
};
