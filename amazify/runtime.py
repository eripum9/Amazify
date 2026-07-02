from __future__ import annotations

import json
from typing import Any

from . import __version__


def build_runtime_script(
    *,
    bridge_url: str,
    bridge_token: str,
    plugins: list[dict[str, Any]],
    catalog_plugins: list[dict[str, Any]] | None = None,
) -> str:
    bridge_url_json = json.dumps(bridge_url)
    bridge_token_json = json.dumps(bridge_token)
    plugins_json = json.dumps(plugins)
    catalog_plugins_json = json.dumps(catalog_plugins or [])
    version_json = json.dumps(__version__)
    return f"""
(() => {{
  const VERSION = {version_json};
  const BRIDGE_URL = {bridge_url_json};
  const BRIDGE_TOKEN = {bridge_token_json};
  const INITIAL_PLUGINS = {plugins_json};
  const INITIAL_CATALOG_PLUGINS = {catalog_plugins_json};
  const RUNTIME_STYLE_ID = "amazify-runtime-style";
  const ROOT_SELECTOR = '[data-amazify-root="true"]';
  const PANEL_SELECTOR = '[data-amazify-panel="true"]';
  const MENU_SELECTOR = '[data-amazify-menu="true"]';

  if (window.Amazify && typeof window.Amazify.cleanup === "function") {{
    window.Amazify.cleanup();
  }}

  const state = {{
    activePanel: null,
    plugins: new Map(),
    catalogPlugins: new Map(),
    root: null,
    actionHost: null,
    observer: null,
    mountedPlugins: new Map(),
    nativeRequests: new Map(),
    nativeSequence: 0,
    lastError: "",
    catalogError: "",
    catalogRefreshInFlight: false,
    bridgeStatus: "Connected"
  }};

  const css = `
    [data-amazify-root="true"] {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: 8px;
      color: #f2f3f3;
      font-family: "Amazon Ember", "Inter", "Segoe UI", Arial, sans-serif;
      position: relative;
      z-index: 2147483600;
      flex: 0 0 auto;
      pointer-events: auto;
    }}
    [data-amazify-root="true"][data-amazify-placement="floating"] {{
      position: fixed;
      top: 14px;
      right: 16px;
      left: auto;
      max-width: calc(100vw - 32px);
      z-index: 2147483644;
      margin-left: 0;
    }}
    [data-amazify-root="true"] button,
    [data-amazify-panel="true"] button,
    [data-amazify-menu="true"] button {{
      font: inherit;
    }}
    .amazify-header-button,
    .amazify-plugin-action {{
      height: 32px;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 18px;
      background: #181a1d;
      color: #f2f3f3;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 0 11px;
      font-size: 13px;
      font-weight: 700;
      line-height: 32px;
      cursor: pointer;
      white-space: nowrap;
      box-shadow: none;
    }}
    .amazify-header-button:hover,
    .amazify-plugin-action:hover {{
      background: #22262a;
      border-color: rgba(0,168,225,0.55);
    }}
    .amazify-mark {{
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: linear-gradient(135deg, #00a8e1, #25d366);
      color: #071014;
      display: inline-grid;
      place-items: center;
      font-size: 12px;
      font-weight: 900;
    }}
    .amazify-plugin-actions {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    [data-amazify-menu="true"] {{
      position: fixed;
      min-width: 284px;
      max-width: 320px;
      background: #181a1d;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 8px;
      box-shadow: 0 18px 44px rgba(0,0,0,0.5);
      color: #f2f3f3;
      font-family: "Amazon Ember", "Inter", "Segoe UI", Arial, sans-serif;
      z-index: 2147483646;
      overflow: hidden;
    }}
    .amazify-menu-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
      background: #101214;
    }}
    .amazify-menu-title {{
      display: flex;
      align-items: center;
      gap: 9px;
      font-size: 14px;
      font-weight: 800;
    }}
    .amazify-menu-status {{
      color: #a9b0b7;
      font-size: 12px;
    }}
    .amazify-menu-body {{
      padding: 7px;
    }}
    .amazify-menu-item {{
      width: 100%;
      min-height: 40px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: #f2f3f3;
      padding: 0 9px;
      font-size: 13px;
      cursor: pointer;
      text-align: left;
    }}
    .amazify-menu-item:hover {{
      background: rgba(255,255,255,0.07);
    }}
    .amazify-menu-item span:last-child {{
      color: #8d969f;
      font-size: 12px;
    }}
    [data-amazify-panel="true"] {{
      position: fixed;
      top: 0;
      right: 0;
      bottom: 0;
      left: auto;
      width: 440px;
      max-width: calc(100vw - 24px);
      background: #101214;
      color: #f2f3f3;
      border-left: 1px solid rgba(255,255,255,0.12);
      box-shadow: -24px 0 52px rgba(0,0,0,0.52);
      z-index: 2147483645;
      display: flex;
      flex-direction: column;
      font-family: "Amazon Ember", "Inter", "Segoe UI", Arial, sans-serif;
    }}
    .amazify-panel-header {{
      min-height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid rgba(255,255,255,0.09);
      background: #15181b;
    }}
    .amazify-panel-title {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .amazify-panel-title strong {{
      display: block;
      font-size: 17px;
      line-height: 20px;
    }}
    .amazify-panel-title small {{
      display: block;
      color: #9ca5ad;
      font-size: 12px;
      line-height: 16px;
      margin-top: 1px;
    }}
    .amazify-close {{
      width: 32px;
      height: 32px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 50%;
      background: transparent;
      color: #c9d0d6;
      cursor: pointer;
      font-size: 22px;
      line-height: 1;
    }}
    .amazify-close:hover {{
      background: rgba(255,255,255,0.08);
      color: #fff;
    }}
    .amazify-tabs {{
      display: flex;
      gap: 3px;
      padding: 10px 14px 0;
      background: #101214;
    }}
    .amazify-tab {{
      flex: 1;
      height: 36px;
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: #aeb6bd;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .amazify-tab[aria-selected="true"] {{
      color: #fff;
      border-bottom-color: #00a8e1;
    }}
    .amazify-panel-body {{
      flex: 1;
      overflow: auto;
      padding: 14px;
    }}
    .amazify-section-title {{
      margin: 14px 2px 8px;
      color: #c6ccd2;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .amazify-plugin-row,
    .amazify-setting-row,
    .amazify-safety-row {{
      border: 1px solid rgba(255,255,255,0.09);
      background: #181a1d;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 9px;
    }}
    .amazify-plugin-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .amazify-plugin-name {{
      color: #fff;
      font-size: 14px;
      font-weight: 800;
      line-height: 18px;
    }}
    .amazify-plugin-meta {{
      color: #97a1aa;
      font-size: 12px;
      line-height: 17px;
      margin-top: 2px;
    }}
    .amazify-plugin-controls {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }}
    .amazify-plugin-desc {{
      color: #c4cad0;
      font-size: 13px;
      line-height: 18px;
      margin-top: 8px;
    }}
    .amazify-permissions {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 9px;
    }}
    .amazify-permission {{
      display: inline-flex;
      align-items: center;
      height: 22px;
      border-radius: 11px;
      background: #22272b;
      border: 1px solid rgba(255,255,255,0.08);
      color: #bbc3ca;
      padding: 0 8px;
      font-size: 11px;
      font-weight: 700;
    }}
    .amazify-toggle {{
      width: 46px;
      height: 26px;
      border: 0;
      border-radius: 13px;
      background: #3a4046;
      position: relative;
      flex: 0 0 auto;
      cursor: pointer;
      padding: 0;
    }}
    .amazify-toggle::after {{
      content: "";
      position: absolute;
      width: 20px;
      height: 20px;
      top: 3px;
      left: 3px;
      border-radius: 50%;
      background: #fff;
      transition: transform 140ms ease;
    }}
    .amazify-toggle[aria-pressed="true"] {{
      background: #00a8e1;
    }}
    .amazify-toggle[aria-pressed="true"]::after {{
      transform: translateX(20px);
    }}
    .amazify-primary,
    .amazify-danger,
    .amazify-quiet {{
      min-height: 34px;
      border: 0;
      border-radius: 17px;
      padding: 0 13px;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }}
    .amazify-primary {{
      background: #00a8e1;
      color: #061116;
    }}
    .amazify-primary:hover {{
      background: #22bceb;
    }}
    .amazify-danger {{
      background: #4a2025;
      color: #ffd7dd;
    }}
    .amazify-danger:hover {{
      background: #5d2830;
    }}
    .amazify-quiet {{
      background: #23282d;
      color: #f2f3f3;
    }}
    .amazify-quiet:hover {{
      background: #2b3137;
    }}
    .amazify-setting-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .amazify-setting-row strong,
    .amazify-safety-row strong {{
      display: block;
      font-size: 13px;
      line-height: 18px;
    }}
    .amazify-setting-row span,
    .amazify-safety-row span {{
      display: block;
      margin-top: 2px;
      color: #a9b1b8;
      font-size: 12px;
      line-height: 17px;
    }}
    .amazify-error {{
      color: #ffb3bd;
      background: #351820;
      border: 1px solid rgba(255,120,140,0.35);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 12px;
      line-height: 17px;
      margin-bottom: 10px;
    }}
    .amazify-empty {{
      color: #a9b1b8;
      border: 1px dashed rgba(255,255,255,0.14);
      border-radius: 8px;
      padding: 18px 12px;
      text-align: center;
      font-size: 13px;
      line-height: 19px;
    }}
    @media (max-width: 520px) {{
      [data-amazify-root="true"][data-amazify-placement="floating"] {{
        top: 10px;
        right: 10px;
        max-width: calc(100vw - 20px);
      }}
      [data-amazify-panel="true"] {{
        width: 100vw;
        max-width: 100vw;
      }}
      .amazify-panel-header {{
        padding: 0 14px;
      }}
      .amazify-panel-body {{
        padding: 12px;
      }}
    }}
  `;

  function installRuntimeStyle() {{
    const existingRuntimeStyle = document.getElementById(RUNTIME_STYLE_ID);
    if (existingRuntimeStyle) existingRuntimeStyle.remove();
    const style = document.createElement("style");
    style.id = RUNTIME_STYLE_ID;
    style.textContent = css;
    document.head.appendChild(style);
  }}

  function esc(value) {{
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({{
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }}[char]));
  }}

  function removeRuntimeSurfaces() {{
    document.querySelectorAll(`${{ROOT_SELECTOR}}, ${{PANEL_SELECTOR}}, ${{MENU_SELECTOR}}`).forEach((node) => node.remove());
  }}

  function findSearchInput() {{
    return Array.from(document.querySelectorAll("input")).find((input) => {{
      const placeholder = String(input.getAttribute("placeholder") || "").toLowerCase();
      const type = String(input.getAttribute("type") || "").toLowerCase();
      return type === "search" || placeholder.includes("search") || placeholder.includes("suche");
    }}) || document.querySelector('[role="search"] input');
  }}

  function isVisibleHeaderHost(candidate) {{
    if (!(candidate instanceof HTMLElement) || candidate === document.body) {{
      return false;
    }}
    const rect = candidate.getBoundingClientRect();
    const style = getComputedStyle(candidate);
    return rect.width > 0 && rect.height > 0 && rect.top < 120 && style.display !== "none" && style.visibility !== "hidden";
  }}

  function findHeaderHost() {{
    const search = findSearchInput();
    const candidates = [];
    if (search) {{
      const searchRole = search.closest('[role="search"]');
      if (searchRole && searchRole.parentElement) candidates.push(searchRole.parentElement);
      let current = search.parentElement;
      for (let depth = 0; current && depth < 5; depth += 1, current = current.parentElement) {{
        if (current.closest("header")) candidates.push(current);
      }}
    }}
    candidates.push(
      document.querySelector('header [class*="right"]'),
      document.querySelector('header [class*="Right"]'),
      document.querySelector("header")
    );
    return candidates.find(isVisibleHeaderHost) || document.body;
  }}

  function createRoot() {{
    const root = document.createElement("div");
    root.dataset.amazifyRoot = "true";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "amazify-header-button";
    button.setAttribute("aria-label", "Open Amazify");
    button.innerHTML = '<span class="amazify-mark">A</span><span>Amazify</span>';
    button.addEventListener("click", (event) => {{
      event.stopPropagation();
      toggleMenu(button);
    }});

    const actions = document.createElement("span");
    actions.className = "amazify-plugin-actions";
    actions.dataset.amazifyActions = "true";

    root.append(button, actions);
    state.root = root;
    state.actionHost = actions;
    return root;
  }}

  function attachRoot() {{
    const host = findHeaderHost();
    if (state.root && state.root.isConnected && state.root.parentElement === host) {{
      return;
    }}
    const existing = document.querySelector(ROOT_SELECTOR);
    if (existing) {{
      existing.remove();
    }}
    const root = createRoot();
    root.dataset.amazifyPlacement = host === document.body ? "floating" : "header";
    host.appendChild(root);
  }}

  function positionMenu(menu, anchor) {{
    const rect = anchor.getBoundingClientRect();
    menu.style.top = `${{Math.max(8, rect.bottom + 8)}}px`;
    const left = Math.min(window.innerWidth - menu.offsetWidth - 10, Math.max(8, rect.left));
    menu.style.left = `${{left}}px`;
  }}

  function toggleMenu(anchor) {{
    const existing = document.querySelector(MENU_SELECTOR);
    if (existing) {{
      existing.remove();
      return;
    }}
    renderMenu(anchor);
  }}

  function renderMenu(anchor) {{
    const existingMenu = document.querySelector(MENU_SELECTOR);
    if (existingMenu) existingMenu.remove();
    const menu = document.createElement("div");
    menu.dataset.amazifyMenu = "true";
    const enabledCount = [...state.plugins.values()].filter((plugin) => plugin.enabled).length;
    menu.innerHTML = `
      <div class="amazify-menu-head">
        <div class="amazify-menu-title"><span class="amazify-mark">A</span><span>Amazify</span></div>
        <div class="amazify-menu-status">${{esc(enabledCount)}} active</div>
      </div>
      <div class="amazify-menu-body">
        <button class="amazify-menu-item" type="button" data-amazify-open="marketplace">
          <span>Marketplace</span><span>Plugins</span>
        </button>
        <button class="amazify-menu-item" type="button" data-amazify-open="settings">
          <span>Settings</span><span>Safety</span>
        </button>
        <button class="amazify-menu-item" type="button" data-amazify-disable-all>
          <span>Disable plugins</span><span>One click</span>
        </button>
      </div>
    `;
    document.body.appendChild(menu);
    positionMenu(menu, anchor);
    menu.querySelector('[data-amazify-open="marketplace"]').addEventListener("click", () => openPanel("marketplace"));
    menu.querySelector('[data-amazify-open="settings"]').addEventListener("click", () => openPanel("settings"));
    menu.querySelector("[data-amazify-disable-all]").addEventListener("click", async () => {{
      await disableAllPlugins();
      const menuAfterDisable = document.querySelector(MENU_SELECTOR);
      if (menuAfterDisable) menuAfterDisable.remove();
    }});
  }}

  function closeMenuOnOutsideClick(event) {{
    const menu = document.querySelector(MENU_SELECTOR);
    if (!menu) return;
    if (menu.contains(event.target) || (state.root && state.root.contains(event.target))) return;
    menu.remove();
  }}

  function ensurePanel() {{
    let panel = document.querySelector(PANEL_SELECTOR);
    if (panel) {{
      return panel;
    }}
    panel = document.createElement("div");
    panel.dataset.amazifyPanel = "true";
    document.body.appendChild(panel);
    return panel;
  }}

  function openPanel(tab = "marketplace") {{
    state.activePanel = tab;
    const existingMenu = document.querySelector(MENU_SELECTOR);
    if (existingMenu) existingMenu.remove();
    renderPanel();
    if (tab === "marketplace") {{
      refreshCatalogFromBridge();
    }}
  }}

  function closePanel() {{
    state.activePanel = null;
    const existingPanel = document.querySelector(PANEL_SELECTOR);
    if (existingPanel) existingPanel.remove();
  }}

  function renderPanel() {{
    const panel = ensurePanel();
    const active = state.activePanel || "marketplace";
    panel.innerHTML = `
      <div class="amazify-panel-header">
        <div class="amazify-panel-title">
          <span class="amazify-mark">A</span>
          <span><strong>Amazify</strong><small>Runtime customization for Amazon Music</small></span>
        </div>
        <button class="amazify-close" type="button" aria-label="Close Amazify">&times;</button>
      </div>
      <div class="amazify-tabs" role="tablist">
        <button class="amazify-tab" type="button" role="tab" data-amazify-tab="marketplace" aria-selected="${{active === "marketplace"}}">Marketplace</button>
        <button class="amazify-tab" type="button" role="tab" data-amazify-tab="settings" aria-selected="${{active === "settings"}}">Settings</button>
      </div>
      <div class="amazify-panel-body">
        ${{state.lastError ? `<div class="amazify-error">${{esc(state.lastError)}}</div>` : ""}}
        ${{active === "settings" ? renderSettings() : renderMarketplace()}}
      </div>
    `;
    panel.querySelector(".amazify-close").addEventListener("click", closePanel);
    panel.querySelectorAll("[data-amazify-tab]").forEach((tab) => {{
      tab.addEventListener("click", () => {{
        state.activePanel = tab.dataset.amazifyTab;
        renderPanel();
        if (state.activePanel === "marketplace") {{
          refreshCatalogFromBridge();
        }}
      }});
    }});
    panel.querySelectorAll("[data-amazify-toggle-plugin]").forEach((toggle) => {{
      toggle.addEventListener("click", async () => {{
        const pluginId = toggle.dataset.amazifyTogglePlugin;
        const enabled = toggle.getAttribute("aria-pressed") !== "true";
        await setPluginEnabled(pluginId, enabled);
      }});
    }});
    panel.querySelectorAll("[data-amazify-refresh]").forEach((button) => {{
      button.addEventListener("click", refreshFromBridge);
    }});
    const disableAllButton = panel.querySelector("[data-amazify-disable-all]");
    if (disableAllButton) disableAllButton.addEventListener("click", disableAllPlugins);
    panel.querySelectorAll("[data-amazify-install-plugin]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        await installPlugin(button.dataset.amazifyInstallPlugin);
      }});
    }});
  }}

  function renderMarketplace() {{
    const plugins = marketplacePlugins();
    if (!plugins.length) {{
      return '<div class="amazify-empty">No marketplace plugins were found. Check the catalog URL in settings or try refresh.</div>';
    }}
    return `
      ${{state.catalogError ? `<div class="amazify-error">${{esc(state.catalogError)}}</div>` : ""}}
      <div class="amazify-section-title">Marketplace plugins</div>
      ${{plugins.map(renderPluginRow).join("")}}
    `;
  }}

  function marketplacePlugins() {{
    const merged = new Map();
    for (const catalogPlugin of state.catalogPlugins.values()) {{
      if (!catalogPlugin || !catalogPlugin.manifest || !catalogPlugin.manifest.id) continue;
      merged.set(catalogPlugin.manifest.id, {{
        catalog: catalogPlugin,
        installed: state.plugins.get(catalogPlugin.manifest.id) || null
      }});
    }}
    for (const installed of state.plugins.values()) {{
      if (!installed || !installed.manifest || !installed.manifest.id) continue;
      if (!merged.has(installed.manifest.id)) {{
        merged.set(installed.manifest.id, {{
          catalog: null,
          installed
        }});
      }}
    }}
    return [...merged.values()].sort((a, b) => {{
      const aChannel = a.catalog ? String(a.catalog.channel || "") : "local";
      const bChannel = b.catalog ? String(b.catalog.channel || "") : "local";
      if (aChannel !== bChannel) return aChannel.localeCompare(bChannel);
      return String((a.installed || a.catalog).manifest.name).localeCompare(String((b.installed || b.catalog).manifest.name));
    }});
  }}

  function renderPluginRow(plugin) {{
    const installed = plugin.installed;
    const catalog = plugin.catalog;
    const manifest = (installed || catalog).manifest;
    const isInstalled = Boolean(installed);
    const channel = catalog ? String(catalog.channel || "community") : "local";
    const metaVersion = isInstalled ? installed.manifest.version : manifest.version;
    const permissions = (manifest.permissions || []).map((permission) => `<span class="amazify-permission">${{esc(permission)}}</span>`).join("");
    const downloadButton = catalog
      ? `<button class="amazify-primary" type="button" data-amazify-install-plugin="${{esc(manifest.id)}}">${{isInstalled ? (catalog.updateAvailable ? "Update" : "Reinstall") : "Download"}}</button>`
      : "";
    const toggleButton = isInstalled
      ? `<button class="amazify-toggle" type="button" aria-label="Toggle ${{esc(manifest.name)}}" aria-pressed="${{installed.enabled ? "true" : "false"}}" data-amazify-toggle-plugin="${{esc(manifest.id)}}"></button>`
      : "";
    return `
      <div class="amazify-plugin-row" data-amazify-plugin-id="${{esc(manifest.id)}}">
        <div class="amazify-plugin-top">
          <div>
            <div class="amazify-plugin-name">${{esc(manifest.name)}}</div>
            <div class="amazify-plugin-meta">${{esc(channel)}} ${{esc(manifest.type)}} by ${{esc(manifest.author)}} - v${{esc(metaVersion)}}${{isInstalled ? " installed" : ""}}${{catalog && isInstalled && catalog.updateAvailable ? ` - update ${{esc(catalog.latestVersion || catalog.manifest.version)}} available` : ""}}</div>
          </div>
          <div class="amazify-plugin-controls">${{downloadButton}}${{toggleButton}}</div>
        </div>
        <div class="amazify-plugin-desc">${{esc(manifest.description)}}</div>
        <div class="amazify-permissions">${{permissions || '<span class="amazify-permission">no special permissions</span>'}}</div>
      </div>
    `;
  }}

  function renderSettings() {{
    const pluginCount = state.plugins.size;
    const catalogCount = state.catalogPlugins.size;
    const enabledCount = [...state.plugins.values()].filter((plugin) => plugin.enabled).length;
    return `
      <div class="amazify-section-title">Status</div>
      <div class="amazify-setting-row">
        <div><strong>Bridge</strong><span>${{esc(state.bridgeStatus)}} at ${{esc(BRIDGE_URL)}}</span></div>
        <button class="amazify-quiet" type="button" data-amazify-refresh>Refresh</button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Plugins</strong><span>${{esc(enabledCount)}} enabled from ${{esc(pluginCount)}} installed</span></div>
        <button class="amazify-danger" type="button" data-amazify-disable-all>Disable all</button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Catalog</strong><span>${{esc(catalogCount)}} entries loaded${{state.catalogError ? ` - ${{esc(state.catalogError)}}` : ""}}</span></div>
        <button class="amazify-quiet" type="button" data-amazify-refresh>Refresh</button>
      </div>

      <div class="amazify-section-title">Safety</div>
      <div class="amazify-safety-row"><strong>Amazify customizes Amazon Music at runtime through a local DevTools connection.</strong><span>Enhanced injection should stay opt-in.</span></div>
      <div class="amazify-safety-row"><strong>It does not modify Amazon Music files on disk.</strong><span>Runtime nodes, styles, and plugin state are removable.</span></div>
      <div class="amazify-safety-row"><strong>Plugins can change what the Amazon Music page displays.</strong><span>Marketplace plugins should be tested and open source; third-party plugins need extra care.</span></div>
      <div class="amazify-safety-row"><strong>Only install plugins from sources you trust.</strong><span>Local plugins are loaded from the Amazify plugin folder.</span></div>
      <div class="amazify-safety-row"><strong>The small background companion only handles Amazon Music connection, plugin files, and local commands.</strong><span>It binds the bridge to localhost only.</span></div>
    `;
  }}

  async function fetchBridge(path, options = {{}}) {{
    const response = await fetch(`${{BRIDGE_URL}}${{path}}`, {{
      ...options,
      headers: {{
        "Content-Type": "application/json",
        "X-Amazify-Token": BRIDGE_TOKEN,
        ...(options.headers || {{}})
      }}
    }});
    const data = await response.json();
    if (!response.ok || data.error) {{
      throw new Error(data.error || `Bridge request failed: ${{response.status}}`);
    }}
    return data;
  }}

  function nativeCommand(name, payload = {{}}) {{
    return new Promise((resolve, reject) => {{
      if (typeof window.AmazifyNativeCommand !== "function") {{
        reject(new Error("Local bridge unavailable"));
        return;
      }}
      const id = `${{Date.now()}}-${{++state.nativeSequence}}`;
      const timeout = setTimeout(() => {{
        state.nativeRequests.delete(id);
        reject(new Error("Native bridge timed out"));
      }}, 5000);
      state.nativeRequests.set(id, {{ resolve, reject, timeout }});
      window.AmazifyNativeCommand(JSON.stringify({{ id, name, payload }}));
    }});
  }}

  function receiveNativeResult(id, result) {{
    const request = state.nativeRequests.get(id);
    if (!request) return false;
    clearTimeout(request.timeout);
    state.nativeRequests.delete(id);
    if (result && result.ok === false) {{
      request.reject(new Error(result.error || "Native bridge command failed"));
    }} else {{
      request.resolve(result);
    }}
    return true;
  }}

  async function bridgeCommand(name, payload = {{}}) {{
    try {{
      if (name === "state.get") {{
        return await fetchBridge("/state");
      }}
      if (name === "plugins.enable") {{
        return await fetchBridge("/plugins/enable", {{
          method: "POST",
          body: JSON.stringify({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "plugins.disable") {{
        return await fetchBridge("/plugins/disable", {{
          method: "POST",
          body: JSON.stringify({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "plugins.install") {{
        return await fetchBridge("/plugins/install", {{
          method: "POST",
          body: JSON.stringify({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "catalog.refresh") {{
        return await fetchBridge("/command", {{
          method: "POST",
          body: JSON.stringify({{ name, payload }})
        }});
      }}
      return await fetchBridge("/command", {{
        method: "POST",
        body: JSON.stringify({{ name, payload }})
      }});
    }} catch (error) {{
      const result = await nativeCommand(name, payload);
      state.bridgeStatus = "Connected through DevTools binding";
      return result;
    }}
  }}

  async function refreshFromBridge() {{
    try {{
      const data = await bridgeCommand("state.get");
      state.bridgeStatus = data && data.bridge && data.bridge.type === "devtools-binding" ? "Connected through DevTools binding" : "Connected";
      state.lastError = "";
      syncStatePayload(data);
    }} catch (error) {{
      state.bridgeStatus = "Unavailable";
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  async function refreshCatalogFromBridge() {{
    if (state.catalogRefreshInFlight) {{
      return;
    }}
    state.catalogRefreshInFlight = true;
    try {{
      const data = await bridgeCommand("catalog.refresh", {{}});
      state.lastError = "";
      syncStatePayload(data);
    }} catch (error) {{
      state.catalogError = error.message || String(error);
      renderPanel();
    }} finally {{
      state.catalogRefreshInFlight = false;
    }}
  }}

  async function setPluginEnabled(pluginId, enabled) {{
    try {{
      const data = await bridgeCommand(enabled ? "plugins.enable" : "plugins.disable", {{ pluginId }});
      state.lastError = "";
      syncStatePayload(data);
    }} catch (error) {{
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  async function disableAllPlugins() {{
    try {{
      const data = await bridge.command("plugins.disableAll", {{}});
      state.lastError = "";
      syncStatePayload(data);
    }} catch (error) {{
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  async function installPlugin(pluginId) {{
    if (!pluginId) return;
    try {{
      state.lastError = "";
      const data = await bridgeCommand("plugins.install", {{ pluginId }});
      syncStatePayload(data);
    }} catch (error) {{
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  function mountPlugin(plugin) {{
    const manifest = plugin.manifest;
    const pluginId = manifest.id;
    unmountPlugin(pluginId);

    const styles = plugin.source && plugin.source.styles ? plugin.source.styles : [];
    for (const styleSource of styles) {{
      const style = document.createElement("style");
      style.dataset.amazifyStyleId = pluginId;
      style.dataset.amazifyPluginId = pluginId;
      style.textContent = String(styleSource.content || "");
      document.head.appendChild(style);
    }}

    let cleanup = null;
    const entry = plugin.source ? plugin.source.entry : "";
    if (entry) {{
      const runner = new Function("Amazify", "manifest", "source", `${{entry}}\\n//# sourceURL=amazify-plugin-${{pluginId}}.js`);
      const result = runner(window.Amazify, manifest, plugin.source);
      if (typeof result === "function") {{
        cleanup = result;
      }}
    }}

    state.mountedPlugins.set(pluginId, {{ cleanup }});
  }}

  function unmountPlugin(pluginId) {{
    const mounted = state.mountedPlugins.get(pluginId);
    if (mounted && typeof mounted.cleanup === "function") {{
      try {{
        mounted.cleanup();
      }} catch (error) {{
        console.warn("[Amazify] Plugin cleanup failed", pluginId, error);
      }}
    }}
    document.querySelectorAll(`[data-amazify-plugin-id="${{cssEscape(pluginId)}}"], [data-amazify-style-id="${{cssEscape(pluginId)}}"]`).forEach((node) => node.remove());
    state.mountedPlugins.delete(pluginId);
  }}

  function syncPlugins(pluginList) {{
    const incoming = new Map();
    for (const plugin of pluginList || []) {{
      if (!plugin || !plugin.manifest || !plugin.manifest.id) continue;
      incoming.set(plugin.manifest.id, plugin);
    }}
    for (const pluginId of state.mountedPlugins.keys()) {{
      const next = incoming.get(pluginId);
      if (!next || !next.enabled) {{
        unmountPlugin(pluginId);
      }}
    }}
    state.plugins = incoming;
    if (window.Amazify) {{
      window.Amazify.plugins = state.plugins;
    }}
    for (const plugin of incoming.values()) {{
      if (plugin.enabled) {{
        try {{
          mountPlugin(plugin);
        }} catch (error) {{
          state.lastError = `${{plugin.manifest.name}} failed: ${{error.message || error}}`;
          console.warn("[Amazify] Plugin mount failed", plugin.manifest.id, error);
        }}
      }}
    }}
    attachRoot();
    if (state.activePanel) {{
      renderPanel();
    }}
  }}

  function syncCatalog(pluginList, error = "") {{
    const incoming = new Map();
    for (const plugin of pluginList || []) {{
      if (!plugin || !plugin.manifest || !plugin.manifest.id) continue;
      incoming.set(plugin.manifest.id, plugin);
    }}
    state.catalogPlugins = incoming;
    state.catalogError = error || "";
    if (window.Amazify) {{
      window.Amazify.catalogPlugins = state.catalogPlugins;
    }}
    if (state.activePanel) {{
      renderPanel();
    }}
  }}

  function syncStatePayload(data) {{
    if (Array.isArray(data.catalogPlugins)) {{
      syncCatalog(data.catalogPlugins, data.catalogError || "");
    }}
    if (Array.isArray(data.runtimePlugins)) {{
      syncPlugins(data.runtimePlugins);
    }}
  }}

  function cssEscape(value) {{
    if (window.CSS && typeof window.CSS.escape === "function") {{
      return window.CSS.escape(value);
    }}
    return String(value).replace(/["\\\\]/g, "\\\\$&");
  }}

  const bridge = {{
    getState: refreshFromBridge,
    command: async (name, payload = {{}}) => bridgeCommand(name, payload)
  }};

  window.Amazify = {{
    version: VERSION,
    plugins: state.plugins,
    catalogPlugins: state.catalogPlugins,
    ui: {{
      openMarketplace: () => openPanel("marketplace"),
      openSettings: () => openPanel("settings"),
      closePanel,
      addHeaderAction: (pluginId, label, onClick) => {{
        attachRoot();
        const action = document.createElement("button");
        action.type = "button";
        action.className = "amazify-plugin-action";
        action.dataset.amazifyPluginId = pluginId;
        action.textContent = label;
        action.addEventListener("click", (event) => {{
          event.stopPropagation();
          if (onClick) onClick(event);
        }});
        state.actionHost.appendChild(action);
        return action;
      }}
    }},
    bridge,
    mountPlugin,
    unmountPlugin,
    syncPlugins,
    receiveNativeResult,
    cleanup: () => {{
      if (state.observer) {{
        state.observer.disconnect();
      }}
      for (const pluginId of [...state.mountedPlugins.keys()]) {{
        unmountPlugin(pluginId);
      }}
      removeRuntimeSurfaces();
      const runtimeStyle = document.getElementById(RUNTIME_STYLE_ID);
      if (runtimeStyle) runtimeStyle.remove();
      document.removeEventListener("click", closeMenuOnOutsideClick, true);
      delete window.Amazify;
    }}
  }};

  installRuntimeStyle();
  removeRuntimeSurfaces();
  attachRoot();
  syncCatalog(INITIAL_CATALOG_PLUGINS);
  syncPlugins(INITIAL_PLUGINS);
  state.observer = new MutationObserver(() => attachRoot());
  state.observer.observe(document.documentElement, {{ childList: true, subtree: true }});
  document.addEventListener("click", closeMenuOnOutsideClick, true);

  return {{ ok: true, version: VERSION, plugins: INITIAL_PLUGINS.length }};
}})()
""".strip()


def build_cleanup_script() -> str:
    return """
(() => {
  if (window.Amazify && typeof window.Amazify.cleanup === "function") {
    window.Amazify.cleanup();
    return true;
  }
  document.querySelectorAll('[data-amazify-root="true"], [data-amazify-panel="true"], [data-amazify-menu="true"], [data-amazify-plugin-id], [data-amazify-style-id]').forEach((node) => node.remove());
  const runtimeStyle = document.getElementById("amazify-runtime-style");
  if (runtimeStyle) runtimeStyle.remove();
  return true;
})()
""".strip()
