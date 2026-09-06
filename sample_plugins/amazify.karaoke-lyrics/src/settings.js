Karaoke.addSettings = function (Amazify, session) {
  return Amazify.ui.addSettingsSection({
    id: "provider", title: "Lyrics providers",
    render: function (host) {
      const status = document.createElement("p");
      const clear = document.createElement("button");
      clear.type = "button";
      clear.textContent = "Clear lyrics cache";
      host.appendChild(status);
      host.appendChild(clear);
      let alive = true;
      const unsubscribe = session.subscribe(function (snapshot) {
        status.textContent = snapshot.status === "ready" ? "Rich lyrics: " + snapshot.source : snapshot.status === "loading" ? "Checking Better Lyrics and Unison" : "Native lyrics (no rich enhancement)";
      });
      clear.addEventListener("click", function () {
        clear.disabled = true;
        Amazify.lyricsProvider.clearCache().then(function () {
          if (alive) status.textContent = "Lyrics cache cleared";
        }).catch(function () { if (alive) status.textContent = "Could not clear lyrics cache"; }).then(function () { if (alive) clear.disabled = false; });
      });
      return function () { alive = false; unsubscribe(); };
    }
  });
};
