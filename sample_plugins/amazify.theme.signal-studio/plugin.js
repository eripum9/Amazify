const pluginId = manifest.id;
const bodyClass = "amazify-signal-studio";
const queueClass = "signal-studio-queue-active";
const bigModeClass = "signal-studio-big-mode-active";
const ownedNodes = new Set();
const originalPlaceholders = new Map();
const movedNodes = [];
const actionProxies = new Map();
let frame = 0;
let transportObserver = null;
let observedTransport = null;
let wasBigModeActive = false;
let settingsCleanup = null;

const themeSettingProperties = [
  "--signal-primary",
  "--signal-secondary",
  "--signal-primary-rgb",
  "--signal-secondary-rgb"
];
const originalThemeSettingProperties = new Map(
  themeSettingProperties.map((property) => [
    property,
    {
      value: document.body.style.getPropertyValue(property),
      priority: document.body.style.getPropertyPriority(property)
    }
  ])
);

function normalizedColor(value, fallback) {
  const color = String(value || "").trim().toLowerCase();
  return /^#[0-9a-f]{6}$/.test(color) ? color : fallback;
}

function colorChannels(color) {
  return [1, 3, 5]
    .map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16))
    .join(" ");
}

function applyThemeSettings(settings = {}) {
  const primary = normalizedColor(settings.primaryColor, "#d9ff43");
  const secondary = normalizedColor(settings.secondaryColor, "#ff745c");
  document.body.style.setProperty("--signal-primary", primary);
  document.body.style.setProperty("--signal-secondary", secondary);
  document.body.style.setProperty("--signal-primary-rgb", colorChannels(primary));
  document.body.style.setProperty("--signal-secondary-rgb", colorChannels(secondary));
}

document.body.classList.add(bodyClass);
document.body.dataset.amazifyTheme = "signal-studio";
if (Amazify.settings && typeof Amazify.settings.subscribe === "function") {
  settingsCleanup = Amazify.settings.subscribe(applyThemeSettings);
} else {
  applyThemeSettings();
}

function own(node) {
  node.dataset.amazifyPluginId = pluginId;
  ownedNodes.add(node);
  return node;
}

function createTopbarPortal() {
  let portal = document.querySelector('[data-signal-studio="topbar"]');
  if (!portal) {
    portal = own(document.createElement("div"));
    portal.className = "signal-studio-topbar";
    portal.dataset.signalStudio = "topbar";
    document.body.appendChild(portal);
  }

  const candidates = [
    document.querySelector("#appchrome .historyNavButtons"),
    document.querySelector("#appchrome .middleSection"),
    document.querySelector("#appchrome .rightSection")
  ].filter(Boolean);

  candidates.forEach((node) => {
    if (node.parentElement === portal) return;
    movedNodes.push({ node, parent: node.parentElement, next: node.nextSibling });
    node.dataset.signalStudioPortal = "true";
    portal.appendChild(node);
  });
}

function positionAmazifyMenu(anchor) {
  requestAnimationFrame(() => {
    const menu = document.querySelector('[data-amazify-menu="true"]');
    if (!menu) return;
    const rect = anchor.getBoundingClientRect();
    const left = Math.min(
      window.innerWidth - menu.offsetWidth - 10,
      Math.max(8, rect.left)
    );
    menu.style.top = `${Math.max(8, rect.bottom + 8)}px`;
    menu.style.right = "auto";
    menu.style.left = `${left}px`;
  });
}

function pluginActionIsEnabled(original) {
  const pluginId = original.dataset.amazifyPluginId;
  const plugins = window.Amazify && window.Amazify.plugins;
  if (!pluginId || !plugins || typeof plugins.get !== "function") return false;
  const plugin = plugins.get(pluginId);
  return Boolean(plugin && plugin.enabled);
}

function restoreDetachedPluginActions(sourceRoot) {
  const actionHost = sourceRoot.querySelector('[data-amazify-actions="true"]');
  if (!actionHost) return;

  const mountedPluginIds = new Set(
    Array.from(actionHost.querySelectorAll("button"))
      .map((button) => button.dataset.amazifyPluginId)
      .filter(Boolean)
  );

  actionProxies.forEach((entry, original) => {
    if (!original.classList.contains("amazify-plugin-action")) return;
    const pluginId = original.dataset.amazifyPluginId;
    if (!pluginActionIsEnabled(original) || mountedPluginIds.has(pluginId)) return;
    actionHost.appendChild(original);
    mountedPluginIds.add(pluginId);
  });
}

function createAmazifyActions() {
  const rightSection = document.querySelector(
    ".signal-studio-topbar .rightSection"
  );
  const sourceRoot = document.querySelector('[data-amazify-root="true"]');
  if (!rightSection || !sourceRoot) return;

  restoreDetachedPluginActions(sourceRoot);

  let proxyRoot = document.querySelector('[data-signal-studio="actions"]');
  if (!proxyRoot) {
    proxyRoot = own(document.createElement("div"));
    proxyRoot.className = "signal-studio-actions";
    proxyRoot.dataset.signalStudio = "actions";
    const profile = rightSection.querySelector(".profile");
    rightSection.insertBefore(proxyRoot, profile || null);
  }

  const originals = Array.from(sourceRoot.querySelectorAll("button"));
  actionProxies.forEach((entry, original) => {
    if (originals.includes(original)) return;
    entry.proxy.remove();
    actionProxies.delete(original);
  });

  originals.forEach((original) => {
    let entry = actionProxies.get(original);
    if (!entry) {
      const proxy = document.createElement("button");
      proxy.type = "button";
      proxy.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        original.click();
        if (original.classList.contains("amazify-header-button")) {
          positionAmazifyMenu(proxy);
        }
      });
      proxyRoot.appendChild(proxy);
      entry = { proxy, signature: "" };
      actionProxies.set(original, entry);
    }

    const signature = [
      original.className,
      original.innerHTML,
      original.getAttribute("aria-label") || "",
      original.getAttribute("aria-pressed") || "",
      original.title || "",
      original.disabled ? "disabled" : "enabled"
    ].join("|");
    if (signature === entry.signature) return;
    entry.signature = signature;
    entry.proxy.className = `${original.className} signal-studio-action-proxy`;
    entry.proxy.innerHTML = original.innerHTML;
    entry.proxy.disabled = original.disabled;
    ["aria-label", "aria-pressed", "title"].forEach((attribute) => {
      const value = original.getAttribute(attribute);
      if (value === null) entry.proxy.removeAttribute(attribute);
      else entry.proxy.setAttribute(attribute, value);
    });
  });

  originals.forEach((original, index) => {
    const entry = actionProxies.get(original);
    if (!entry || proxyRoot.children[index] === entry.proxy) return;
    proxyRoot.insertBefore(entry.proxy, proxyRoot.children[index] || null);
  });
}

function createAmbience() {
  if (document.querySelector('[data-signal-studio="ambience"]')) return;
  const ambience = own(document.createElement("div"));
  ambience.className = "signal-studio-ambience";
  ambience.dataset.signalStudio = "ambience";
  ambience.setAttribute("aria-hidden", "true");
  document.body.prepend(ambience);
}

function updateSearch() {
  document.querySelectorAll(
    '.signal-studio-topbar .searchBarInput, #appchrome .searchBarInput'
  ).forEach((input) => {
    if (!originalPlaceholders.has(input)) {
      originalPlaceholders.set(input, input.getAttribute("placeholder"));
    }
    input.setAttribute("placeholder", "Search music, artists, podcasts");
    input.setAttribute("aria-label", "Search music, artists, and podcasts");
  });
}

function updateSearchSuggestions() {
  const anchor = document.querySelector(
    '.signal-studio-topbar .searchBar, #appchrome .searchBar'
  );
  const suggestions = document.querySelector(".searchSuggestions");
  if (!anchor || !suggestions) {
    document.body.style.removeProperty("--signal-search-left");
    document.body.style.removeProperty("--signal-search-top");
    document.body.style.removeProperty("--signal-search-width");
    return;
  }

  const rect = anchor.getBoundingClientRect();
  const viewportPadding = 8;
  const width = Math.max(220, rect.width);
  const left = Math.min(
    window.innerWidth - width - viewportPadding,
    Math.max(viewportPadding, rect.left)
  );
  document.body.style.setProperty("--signal-search-left", `${left}px`);
  document.body.style.setProperty(
    "--signal-search-top",
    `${Math.min(window.innerHeight - 56, rect.bottom + 8)}px`
  );
  document.body.style.setProperty("--signal-search-width", `${width}px`);
}

function updateChildViewState() {
  const transport = document.querySelector("#transportContainer.childViewShowing");
  const isBigMode = Boolean(
    transport &&
    transport.classList.contains("nowPlayingShowing") &&
    transport.querySelector(".nowPlayingView")
  );
  document.body.classList.toggle(
    queueClass,
    Boolean(transport && transport.querySelector(".playQueueContainer"))
  );
  document.body.classList.toggle(bigModeClass, isBigMode);

  if (
    isBigMode &&
    !wasBigModeActive &&
    !document.body.classList.contains("amazify-true-big-mode-active")
  ) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const wrapper = document.querySelector(".nowPlayingView .lyricsWrapper");
        const current = document.querySelector(".nowPlayingView .lyricsLine.current");
        if (!wrapper || !current) return;
        const wrapperRect = wrapper.getBoundingClientRect();
        const currentRect = current.getBoundingClientRect();
        wrapper.scrollTop +=
          currentRect.top +
          currentRect.height / 2 -
          (wrapperRect.top + wrapperRect.height / 2);
      });
    });
  }
  wasBigModeActive = isBigMode;
}

function currentArtwork() {
  const image = document.querySelector(
    "#transportContainer:not(.childViewShowing) .trackMetadataWrapper .albumArt img.artImage, " +
    "#transportContainer .trackMetadataWrapper .albumArt img.artImage"
  );
  return image && image.currentSrc ? image.currentSrc : image && image.src ? image.src : "";
}

function updateNowPlaying() {
  const title = document.querySelector(
    "#transportContainer .trackMetadata .primaryContainer .title, " +
    "#transportContainer .trackMetadata .primaryContainer"
  );
  const name = String(title && title.textContent ? title.textContent : "").trim();
  document.querySelectorAll("[data-signal-now-playing]").forEach((node) => {
    node.textContent = name || "Ready to play";
  });

  const artwork = currentArtwork();
  if (artwork) {
    document.body.style.setProperty("--signal-studio-artwork", `url("${artwork.replace(/"/g, "\\\"")}")`);
    document.body.classList.add("signal-studio-has-artwork");
  } else {
    document.body.style.removeProperty("--signal-studio-artwork");
    document.body.classList.remove("signal-studio-has-artwork");
  }
}

function bindTransportObserver() {
  const transport = document.querySelector("#transportContainer");
  if (!transport || transport === observedTransport) return;
  if (transportObserver) transportObserver.disconnect();
  observedTransport = transport;
  transportObserver = new MutationObserver(scheduleSync);
  transportObserver.observe(transport, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src", "class", "title"]
  });
}

function sync() {
  frame = 0;
  if (!document.body.classList.contains(bodyClass)) return;
  createTopbarPortal();
  createAmazifyActions();
  createAmbience();
  updateSearch();
  updateSearchSuggestions();
  updateChildViewState();
  bindTransportObserver();
  updateNowPlaying();
}

function scheduleSync() {
  if (frame) return;
  frame = requestAnimationFrame(sync);
}

function focusSearch(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
  const input = document.querySelector(
    '.signal-studio-topbar .searchBarInput, #appchrome .searchBarInput'
  );
  if (!input) return;
  event.preventDefault();
  input.focus();
  input.select();
}

const documentObserver = new MutationObserver(scheduleSync);
documentObserver.observe(document.body, { childList: true, subtree: true });
window.addEventListener("hashchange", scheduleSync);
window.addEventListener("resize", scheduleSync);
document.addEventListener("keydown", focusSearch);
sync();

return () => {
  if (settingsCleanup) settingsCleanup();
  documentObserver.disconnect();
  if (transportObserver) transportObserver.disconnect();
  if (frame) cancelAnimationFrame(frame);
  window.removeEventListener("hashchange", scheduleSync);
  window.removeEventListener("resize", scheduleSync);
  document.removeEventListener("keydown", focusSearch);
  originalPlaceholders.forEach((placeholder, input) => {
    if (!input.isConnected) return;
    if (placeholder === null) input.removeAttribute("placeholder");
    else input.setAttribute("placeholder", placeholder);
    input.removeAttribute("aria-label");
  });
  [...movedNodes].reverse().forEach(({ node, parent, next }) => {
    if (!node.isConnected) return;
    node.removeAttribute("data-signal-studio-portal");
    if (!parent || !parent.isConnected) return;
    if (next && next.parentElement === parent) parent.insertBefore(node, next);
    else parent.appendChild(node);
  });
  ownedNodes.forEach((node) => node.remove());
  actionProxies.clear();
  document.body.classList.remove(
    bodyClass,
    "signal-studio-has-artwork",
    queueClass,
    bigModeClass
  );
  delete document.body.dataset.amazifyTheme;
  wasBigModeActive = false;
  document.body.style.removeProperty("--signal-studio-artwork");
  document.body.style.removeProperty("--signal-search-left");
  document.body.style.removeProperty("--signal-search-top");
  document.body.style.removeProperty("--signal-search-width");
  originalThemeSettingProperties.forEach(({ value, priority }, property) => {
    if (value) document.body.style.setProperty(property, value, priority);
    else document.body.style.removeProperty(property);
  });
};
