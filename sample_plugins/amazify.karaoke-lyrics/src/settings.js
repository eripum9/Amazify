Karaoke.addSettings = function (Amazify, session) {
  return Amazify.ui.addSettingsSection({
    id: "provider", title: "Lyrics providers",
    render: function (host) {
      const status = document.createElement("p");
      const clear = document.createElement("button");
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "Retry lyrics lookup";
      retry.addEventListener("click", function () { session.retry(); });
      clear.type = "button";
      clear.textContent = "Clear lyrics cache";
      host.appendChild(status);
      host.appendChild(retry);
      host.appendChild(clear);
      let alive = true;
      const unsubscribe = session.subscribe(function (snapshot) {
        retry.disabled = !snapshot.track || snapshot.status === "loading" || snapshot.status === "ready";
        if (snapshot.status === "ready") {
          status.textContent = "Rich lyrics: " + snapshot.source;
          return;
        }
        if (snapshot.status === "loading") {
          status.textContent = "Checking Better Lyrics and Unison";
          return;
        }
        const provider = snapshot.providerStatus || {};
        let detail = "";
        if (provider.status === "no-lyrics") detail = provider.detail || "No compatible rich lyrics";
        else if (provider.status === "unavailable") detail = provider.detail || "Providers unavailable";
        const attempts = Number(provider.attempts || 0);
        status.textContent = "Native lyrics (no rich enhancement)" + (detail ? " - " + detail : "") + (attempts > 1 ? " (tried " + attempts + " metadata variants)" : "");
      });
      clear.addEventListener("click", function () {
        clear.disabled = true;
        Amazify.lyricsProvider.clearCache().then(function () {
          if (alive) { status.textContent = "Lyrics cache cleared"; session.retry(); }
        }).catch(function () { if (alive) status.textContent = "Could not clear lyrics cache"; }).then(function () { if (alive) clear.disabled = false; });
      });
      return function () { alive = false; unsubscribe(); };
    }
  });
};
