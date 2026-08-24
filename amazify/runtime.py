from __future__ import annotations

import base64
import json
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__


def _runtime_logo_data_uri() -> str:
    logo = _read_runtime_logo()
    return (
        f"data:image/png;base64,{base64.b64encode(logo).decode('ascii')}"
        if logo
        else ""
    )


def _read_runtime_logo() -> bytes:
    candidates: list[object] = []
    try:
        candidates.append(resources.files("amazify").joinpath("assets/logo.png"))
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass

    package_dir = Path(__file__).resolve().parent
    candidates.append(package_dir / "assets" / "logo.png")
    mei_pass = getattr(sys, "_MEIPASS", None)
    if mei_pass:
        candidates.append(Path(mei_pass) / "amazify" / "assets" / "logo.png")

    for candidate in candidates:
        try:
            data = candidate.read_bytes()
        except (FileNotFoundError, OSError, AttributeError):
            continue
        if data:
            return data
    return b""


def build_runtime_script(
    *,
    bridge_url: str,
    bridge_token: str,
    plugins: list[dict[str, Any]],
    catalog_plugins: list[dict[str, Any]] | None = None,
    native_session_nonce: str | None = None,
    native_response_callback: str | None = None,
    app_update: dict[str, Any] | None = None,
) -> str:
    bridge_url_json = json.dumps(bridge_url)
    bridge_token_json = json.dumps(bridge_token)
    plugins_json = json.dumps(plugins)
    catalog_plugins_json = json.dumps(catalog_plugins or [])
    native_session_nonce_json = json.dumps(native_session_nonce or "")
    native_response_callback_json = json.dumps(native_response_callback or "")
    app_update_json = json.dumps(app_update or {})
    version_json = json.dumps(__version__)
    logo_data_uri_json = json.dumps(_runtime_logo_data_uri())
    return f"""
(() => {{
  // Capture bridge primitives before any plugin code mounts. DOM and network
  // permissions disclose renderer access; they are not a JavaScript sandbox.
  const NATIVE_FUNCTION = window.Function;
  const NATIVE_FETCH = typeof window.fetch === "function" ? window.fetch.bind(window) : null;
  const NATIVE_RESPONSE_JSON = window.Response && window.Response.prototype && typeof window.Response.prototype.json === "function"
    ? Function.prototype.call.bind(window.Response.prototype.json)
    : null;
  const NATIVE_COMMAND = typeof window.AmazifyNativeCommand === "function"
    ? window.AmazifyNativeCommand.bind(window)
    : null;
  const NATIVE_CONFIRM = typeof window.confirm === "function" ? window.confirm.bind(window) : () => false;
  const NATIVE_SET_TIMEOUT = window.setTimeout.bind(window);
  const NATIVE_CLEAR_TIMEOUT = window.clearTimeout.bind(window);
  const NATIVE_DEFINE_PROPERTY = Object.defineProperty.bind(Object);
  const NATIVE_ASSIGN = Object.assign.bind(Object);
  const NATIVE_FREEZE = Object.freeze.bind(Object);
  const NATIVE_KEYS = Object.keys.bind(Object);
  const NATIVE_STRING = window.String;
  const NATIVE_SET = window.Set;
  const NATIVE_SET_ADD = Function.prototype.call.bind(Set.prototype.add);
  const NATIVE_SET_HAS = Function.prototype.call.bind(Set.prototype.has);
  const NATIVE_ARRAY_IS_ARRAY = Array.isArray.bind(Array);
  const NATIVE_JSON_PARSE = JSON.parse.bind(JSON);
  const NATIVE_JSON_STRINGIFY = JSON.stringify.bind(JSON);
  const NATIVE_HAS_OWN = Function.prototype.call.bind(Object.prototype.hasOwnProperty);
  const NATIVE_PROMISE = window.Promise;
  const NATIVE_FILE_READER = window.FileReader;
  const NATIVE_FILE_READER_READ_AS_DATA_URL = NATIVE_FILE_READER
    ? Function.prototype.call.bind(NATIVE_FILE_READER.prototype.readAsDataURL)
    : null;
  const NATIVE_MAP = window.Map;
  const NATIVE_MAP_GET = Function.prototype.call.bind(Map.prototype.get);
  const NATIVE_MAP_SET = Function.prototype.call.bind(Map.prototype.set);
  const NATIVE_MAP_HAS = Function.prototype.call.bind(Map.prototype.has);
  const NATIVE_MAP_DELETE = Function.prototype.call.bind(Map.prototype.delete);
  const NATIVE_MAP_FOR_EACH = Function.prototype.call.bind(Map.prototype.forEach);
  const NATIVE_MAP_CLEAR = Function.prototype.call.bind(Map.prototype.clear);
  const NATIVE_DISPATCH_EVENT = Function.prototype.call.bind(EventTarget.prototype.dispatchEvent);
  const NATIVE_ADD_EVENT_LISTENER = Function.prototype.call.bind(EventTarget.prototype.addEventListener);
  const NATIVE_REMOVE_EVENT_LISTENER = Function.prototype.call.bind(EventTarget.prototype.removeEventListener);
  const NATIVE_EVENT = window.Event;
  const CLEANUP_EVENT = "amazify-runtime-cleanup-request";

  // Cleanup may run arbitrary plugin teardown. Keep bridge credentials out of
  // scope until all trusted references needed by the replacement are captured.
  NATIVE_DISPATCH_EVENT(window, new NATIVE_EVENT(CLEANUP_EVENT));
  document.querySelectorAll('[data-amazify-plugin-id], [data-amazify-style-id]').forEach((node) => node.remove());
  if (NATIVE_COMMAND) {{
    try {{
      delete window.AmazifyNativeCommand;
    }} catch (_error) {{
      try {{ window.AmazifyNativeCommand = undefined; }} catch (_ignored) {{}}
    }}
  }}

  const VERSION = {version_json};
  const BRIDGE_URL = {bridge_url_json};
  const BRIDGE_TOKEN = {bridge_token_json};
  const INITIAL_PLUGINS = {plugins_json};
  const INITIAL_CATALOG_PLUGINS = {catalog_plugins_json};
  const INITIAL_APP_UPDATE = {app_update_json};
  const NATIVE_SESSION_NONCE = {native_session_nonce_json};
  const NATIVE_RESPONSE_CALLBACK = {native_response_callback_json};
  const LOGO_DATA_URI = {logo_data_uri_json};
  const RUNTIME_STYLE_ID = "amazify-runtime-style";
  const ROOT_SELECTOR = '[data-amazify-root="true"]';
  const PANEL_SELECTOR = '[data-amazify-panel="true"]';
  const MENU_SELECTOR = '[data-amazify-menu="true"]';
  const SETTINGS_STORAGE_KEY = "amazify.runtime.settings.v1";
  const PLUGIN_SETTINGS_STORAGE_KEY = "amazify.plugin.settings.v1";
  let runtimeActive = true;

  function readRuntimePreferences() {{
    const defaults = {{
      autoCheckUpdates: true,
      autoCheckAppUpdates: true
    }};
    try {{
      const saved = NATIVE_JSON_PARSE(window.localStorage.getItem(SETTINGS_STORAGE_KEY) || "{{}}");
      if (!saved || typeof saved !== "object") return defaults;
      return {{
        autoCheckUpdates: typeof saved.autoCheckUpdates === "boolean" ? saved.autoCheckUpdates : defaults.autoCheckUpdates,
        autoCheckAppUpdates: typeof saved.autoCheckAppUpdates === "boolean" ? saved.autoCheckAppUpdates : defaults.autoCheckAppUpdates
      }};
    }} catch (_error) {{
      return defaults;
    }}
  }}

  function readStoredPluginSettings() {{
    try {{
      const saved = NATIVE_JSON_PARSE(window.localStorage.getItem(PLUGIN_SETTINGS_STORAGE_KEY) || "{{}}");
      return saved && typeof saved === "object" && !NATIVE_ARRAY_IS_ARRAY(saved) ? saved : {{}};
    }} catch (_error) {{
      return {{}};
    }}
  }}

  const state = {{
    activePanel: null,
    activePluginSettingsId: "",
    plugins: new NATIVE_MAP(),
    catalogPlugins: new NATIVE_MAP(),
    root: null,
    actionHost: null,
    observer: null,
    mountedPlugins: new NATIVE_MAP(),
    capabilityProviders: new NATIVE_MAP(),
    capabilitySubscribers: new NATIVE_MAP(),
    settingsSections: new NATIVE_MAP(),
    settingsRenderCleanups: new NATIVE_MAP(),
    pluginSettingSubscribers: new NATIVE_MAP(),
    nativeRequests: new NATIVE_MAP(),
    nativeSequence: 0,
    lastError: "",
    catalogError: "",
    catalogUrl: "",
    catalogRefreshInFlight: false,
    appUpdate: INITIAL_APP_UPDATE,
    appUpdatePollTimer: null,
    bridgeStatus: "Connected",
    preferences: readRuntimePreferences(),
    pluginSettings: readStoredPluginSettings()
  }};

  function mapValuesSnapshot(map) {{
    const values = [];
    NATIVE_MAP_FOR_EACH(map, (value) => {{
      values[values.length] = value;
    }});
    return values;
  }}

  function mapKeysSnapshot(map) {{
    const keys = [];
    NATIVE_MAP_FOR_EACH(map, (_value, key) => {{
      keys[keys.length] = key;
    }});
    return keys;
  }}

  function countMapValues(map, predicate) {{
    let count = 0;
    NATIVE_MAP_FOR_EACH(map, (value) => {{
      if (predicate(value)) count += 1;
    }});
    return count;
  }}

  function manifestForPlugin(pluginId) {{
    const installed = NATIVE_MAP_GET(state.plugins, pluginId);
    if (installed && installed.manifest) return installed.manifest;
    const catalog = NATIVE_MAP_GET(state.catalogPlugins, pluginId);
    return catalog && catalog.manifest ? catalog.manifest : null;
  }}

  function manifestSettings(manifest) {{
    return manifest && NATIVE_ARRAY_IS_ARRAY(manifest.settings) ? manifest.settings : [];
  }}

  function pluginSettingDefinition(manifest, settingId) {{
    const settings = manifestSettings(manifest);
    for (let index = 0; index < settings.length; index += 1) {{
      if (NATIVE_STRING(settings[index].id || "") === settingId) return settings[index];
    }}
    return null;
  }}

  function normalizePluginSettingValue(definition, value) {{
    if (!definition || typeof definition !== "object") return {{ valid: false }};
    const type = NATIVE_STRING(definition.type || "");
    if (type === "boolean") {{
      return typeof value === "boolean" ? {{ valid: true, value }} : {{ valid: false }};
    }}
    if (type === "color") {{
      const color = NATIVE_STRING(value || "").trim().toLowerCase();
      return /^#[0-9a-f]{{6}}$/.test(color)
        ? {{ valid: true, value: color }}
        : {{ valid: false }};
    }}
    if (type === "image") {{
      if (value === "") return {{ valid: true, value: "" }};
      const image = NATIVE_STRING(value || "");
      const match = /^data:([^;,]+);base64,([A-Za-z0-9+/]*={{0,2}})$/.exec(image);
      const accepted = NATIVE_ARRAY_IS_ARRAY(definition.accept) ? definition.accept : [];
      const maxBytes = Math.max(1024, Math.min(2 * 1024 * 1024, Number(definition.maxBytes) || 1024 * 1024));
      if (!match || match[2].length % 4 !== 0 || !accepted.includes(match[1])) return {{ valid: false }};
      const padding = match[2].endsWith("==") ? 2 : match[2].endsWith("=") ? 1 : 0;
      const decodedBytes = match[2].length * 3 / 4 - padding;
      return decodedBytes <= maxBytes ? {{ valid: true, value: image }} : {{ valid: false }};
    }}
    if (type === "range") {{
      const minimum = Number(definition.min);
      const maximum = Number(definition.max);
      const step = Number(definition.step);
      const number = Number(value);
      if (![minimum, maximum, step, number].every(Number.isFinite) || maximum <= minimum || step <= 0) {{
        return {{ valid: false }};
      }}
      const clamped = Math.min(maximum, Math.max(minimum, number));
      const aligned = minimum + Math.round((clamped - minimum) / step) * step;
      return {{ valid: true, value: Number(Math.min(maximum, Math.max(minimum, aligned)).toFixed(8)) }};
    }}
    if (type === "select") {{
      const selected = NATIVE_STRING(value);
      const options = NATIVE_ARRAY_IS_ARRAY(definition.options) ? definition.options : [];
      const valid = options.some((option) => option && NATIVE_STRING(option.value) === selected);
      return valid ? {{ valid: true, value: selected }} : {{ valid: false }};
    }}
    if (type === "text") {{
      const text = NATIVE_STRING(value == null ? "" : value);
      const maxLength = Math.max(1, Math.min(1024, Number(definition.maxLength) || 256));
      return text.length <= maxLength
        ? {{ valid: true, value: text }}
        : {{ valid: false }};
    }}
    return {{ valid: false }};
  }}

  function storedSettingsForPlugin(pluginId, create = false) {{
    let values = NATIVE_HAS_OWN(state.pluginSettings, pluginId) ? state.pluginSettings[pluginId] : null;
    if (!values || typeof values !== "object" || NATIVE_ARRAY_IS_ARRAY(values)) {{
      if (!create) return null;
      values = {{}};
      state.pluginSettings[pluginId] = values;
    }}
    return values;
  }}

  function pluginSettingValue(pluginId, manifest, settingId) {{
    const definition = pluginSettingDefinition(manifest, settingId);
    if (!definition) throw new Error(`Unknown setting: ${{settingId}}`);
    const values = storedSettingsForPlugin(pluginId, false);
    if (values && NATIVE_HAS_OWN(values, settingId)) {{
      const stored = normalizePluginSettingValue(definition, values[settingId]);
      if (stored.valid) return stored.value;
    }}
    return normalizePluginSettingValue(definition, definition.default).value;
  }}

  function pluginSettingsSnapshot(pluginId, manifest) {{
    const snapshot = {{}};
    const definitions = manifestSettings(manifest);
    for (let index = 0; index < definitions.length; index += 1) {{
      const settingId = NATIVE_STRING(definitions[index].id || "");
      if (settingId) snapshot[settingId] = pluginSettingValue(pluginId, manifest, settingId);
    }}
    return freezeDeep(snapshot);
  }}

  function persistPluginSettings() {{
    window.localStorage.setItem(
      PLUGIN_SETTINGS_STORAGE_KEY,
      NATIVE_JSON_STRINGIFY(state.pluginSettings)
    );
  }}

  function notifyPluginSettingSubscribers(pluginId, manifest) {{
    const subscribers = NATIVE_MAP_GET(state.pluginSettingSubscribers, pluginId) || [];
    const snapshot = pluginSettingsSnapshot(pluginId, manifest);
    for (let index = 0; index < subscribers.length; index += 1) {{
      const subscriber = subscribers[index];
      if (!subscriber.active) continue;
      try {{ subscriber.listener(snapshot); }} catch (error) {{
        console.warn("[Amazify] Plugin settings subscriber failed", pluginId, error);
      }}
    }}
  }}

  function setPluginSetting(pluginId, settingId, value) {{
    const manifest = manifestForPlugin(pluginId);
    const definition = pluginSettingDefinition(manifest, settingId);
    if (!definition) throw new Error(`Unknown setting: ${{settingId}}`);
    const normalized = normalizePluginSettingValue(definition, value);
    if (!normalized.valid) throw new TypeError(`Invalid value for setting: ${{settingId}}`);
    const values = storedSettingsForPlugin(pluginId, true);
    const hadPrevious = NATIVE_HAS_OWN(values, settingId);
    const previous = values[settingId];
    values[settingId] = normalized.value;
    try {{
      persistPluginSettings();
    }} catch (_error) {{
      if (hadPrevious) values[settingId] = previous;
      else delete values[settingId];
      throw new Error("Plugin settings storage is full or unavailable");
    }}
    notifyPluginSettingSubscribers(pluginId, manifest);
    return normalized.value;
  }}

  function resetPluginSettings(pluginId) {{
    const manifest = manifestForPlugin(pluginId);
    if (!manifest) return;
    if (NATIVE_HAS_OWN(state.pluginSettings, pluginId)) {{
      const previous = state.pluginSettings[pluginId];
      delete state.pluginSettings[pluginId];
      try {{
        persistPluginSettings();
      }} catch (_error) {{
        state.pluginSettings[pluginId] = previous;
        throw new Error("Plugin settings storage is unavailable");
      }}
    }}
    notifyPluginSettingSubscribers(pluginId, manifest);
  }}

  function subscribePluginSettings(pluginId, listener) {{
    if (typeof listener !== "function") throw new TypeError("Plugin settings subscriber must be a function");
    const manifest = manifestForPlugin(pluginId);
    const subscribers = NATIVE_MAP_GET(state.pluginSettingSubscribers, pluginId) || [];
    const record = {{ active: true, listener }};
    subscribers[subscribers.length] = record;
    NATIVE_MAP_SET(state.pluginSettingSubscribers, pluginId, subscribers);
    listener(pluginSettingsSnapshot(pluginId, manifest));
    return () => {{ record.active = false; }};
  }}

  if (/^__amazifyNativeResult_[0-9a-f]{{36}}$/.test(NATIVE_RESPONSE_CALLBACK)) {{
    NATIVE_DEFINE_PROPERTY(window, NATIVE_RESPONSE_CALLBACK, {{
      value: (id, result) => runtimeActive ? receiveNativeResult(id, result) : false,
      enumerable: false,
      configurable: false,
      writable: false
    }});
  }}

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
      flex: 0 0 auto;
    }}
    .amazify-header-button {{
      gap: 10px;
      padding-left: 9px;
    }}
    .amazify-header-button:hover,
    .amazify-plugin-action:hover {{
      background: #22262a;
      border-color: rgba(0,168,225,0.55);
    }}
    .amazify-logo {{
      width: 20px;
      height: 20px;
      border-radius: 6px;
      display: block;
      flex: 0 0 auto;
      object-fit: cover;
      background: #15181b;
      box-shadow: 0 0 0 1px rgba(255,255,255,0.08);
      user-select: none;
    }}
    .amazify-logo-menu {{
      width: 24px;
      height: 24px;
      border-radius: 7px;
    }}
    .amazify-logo-panel {{
      width: 32px;
      height: 32px;
      border-radius: 8px;
    }}
    .amazify-logo-fallback {{
      border: 1px solid rgba(255,255,255,0.12);
    }}
    .amazify-header-button .amazify-logo {{
      flex: 0 0 20px;
      min-width: 20px;
    }}
    .amazify-header-label {{
      display: inline-block;
      flex: 0 0 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      line-height: 1;
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
    .amazify-marketplace-section + .amazify-marketplace-section {{
      margin-top: 20px;
      padding-top: 4px;
      border-top: 1px solid rgba(255,255,255,0.08);
    }}
    .amazify-plugin-row,
    .amazify-setting-row {{
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
    .amazify-plugin-settings-view {{
      min-width: 0;
    }}
    .amazify-back-button {{
      min-height: 32px;
      border: 0;
      background: transparent;
      color: #aeb6bd;
      padding: 0;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }}
    .amazify-back-button:hover {{
      color: #fff;
    }}
    .amazify-plugin-settings-heading {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
    }}
    .amazify-plugin-settings-heading .amazify-plugin-name {{
      font-size: 18px;
      line-height: 23px;
    }}
    .amazify-plugin-settings-fields {{
      border-top: 1px solid rgba(255,255,255,0.09);
    }}
    .amazify-plugin-setting-field {{
      min-height: 66px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid rgba(255,255,255,0.09);
      padding: 10px 2px;
    }}
    .amazify-plugin-setting-field > div:first-child {{
      min-width: 0;
    }}
    .amazify-plugin-setting-field strong {{
      display: block;
      color: #f2f3f3;
      font-size: 13px;
      line-height: 18px;
    }}
    .amazify-plugin-setting-field span {{
      display: block;
      margin-top: 2px;
      color: #929ca5;
      font-size: 12px;
      line-height: 16px;
    }}
    .amazify-plugin-setting-control {{
      min-width: 126px;
      display: flex;
      justify-content: flex-end;
      flex: 0 0 auto;
    }}
    .amazify-color-setting,
    .amazify-range-setting {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 9px;
    }}
    .amazify-color-setting input[type="color"] {{
      width: 38px;
      height: 32px;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 6px;
      background: #23282d;
      padding: 3px;
      cursor: pointer;
    }}
    .amazify-color-setting code,
    .amazify-range-setting output {{
      min-width: 58px;
      color: #cbd1d6;
      font: 12px/16px "Cascadia Mono", Consolas, monospace;
      text-align: right;
    }}
    .amazify-image-setting {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 7px;
    }}
    .amazify-image-setting-preview,
    .amazify-image-setting-empty {{
      width: 48px;
      height: 48px;
      flex: 0 0 48px;
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 6px;
      background: #23282d;
    }}
    .amazify-image-setting-preview {{
      display: block;
      object-fit: cover;
    }}
    .amazify-image-setting-empty {{
      display: grid;
      place-items: center;
      color: #929ca5;
      font-size: 10px;
      line-height: 12px;
      text-align: center;
    }}
    .amazify-image-setting-choose {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .amazify-image-setting-choose:focus-within {{
      outline: 2px solid #00a8e1;
      outline-offset: 2px;
    }}
    .amazify-image-setting-choose input {{
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      clip-path: inset(50%);
      white-space: nowrap;
    }}
    .amazify-range-setting input[type="range"] {{
      width: 120px;
      accent-color: #00a8e1;
    }}
    .amazify-select-setting,
    .amazify-text-setting {{
      width: 170px;
      max-width: 42vw;
      min-height: 34px;
      border: 1px solid rgba(255,255,255,0.14);
      border-radius: 6px;
      background: #23282d;
      color: #f2f3f3;
      padding: 0 9px;
      font: inherit;
      font-size: 12px;
    }}
    .amazify-plugin-settings-section {{
      margin-top: 14px;
    }}
    .amazify-plugin-settings-host {{
      min-width: 0;
    }}
    .amazify-plugin-settings-actions {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 20px;
      padding-top: 14px;
      border-top: 1px solid rgba(255,255,255,0.09);
    }}
    .amazify-plugin-settings-note {{
      color: #929ca5;
      font-size: 12px;
      line-height: 17px;
      text-align: right;
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
    .amazify-primary:disabled,
    .amazify-danger:disabled,
    .amazify-quiet:disabled {{
      opacity: 0.45;
      cursor: default;
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
    .amazify-setting-row > div {{
      min-width: 0;
    }}
    .amazify-setting-row strong {{
      display: block;
      font-size: 13px;
      line-height: 18px;
    }}
    .amazify-setting-row span {{
      display: block;
      margin-top: 2px;
      color: #a9b1b8;
      font-size: 12px;
      line-height: 17px;
    }}
    .amazify-setting-value {{
      max-width: 250px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .amazify-setting-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }}
    .amazify-setting-row .amazify-runtime-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border-radius: 13px;
      padding: 0 10px;
      background: #23282d;
      color: #dbe0e4;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
      margin-top: 0;
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
      .amazify-plugin-setting-field {{
        align-items: stretch;
        flex-direction: column;
        gap: 8px;
      }}
      .amazify-plugin-setting-control {{
        width: 100%;
        justify-content: flex-start;
      }}
      .amazify-select-setting,
      .amazify-text-setting {{
        width: 100%;
        max-width: none;
      }}
      .amazify-plugin-settings-actions {{
        align-items: stretch;
        flex-direction: column;
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

  function logoMarkup(className = "amazify-logo") {{
    return LOGO_DATA_URI
      ? `<img class="${{className}}" src="${{LOGO_DATA_URI}}" alt="" aria-hidden="true" draggable="false">`
      : `<span class="${{className}} amazify-logo-fallback" aria-hidden="true"></span>`;
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
    button.innerHTML = `${{logoMarkup()}}<span class="amazify-header-label">Amazify</span>`;
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
    if (state.root) {{
      state.root.dataset.amazifyPlacement = host === document.body ? "floating" : "header";
      if (state.root.parentElement !== host) {{
        host.appendChild(state.root);
      }}
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

  function addTrustedLifecycleClick(target, handler) {{
    NATIVE_ADD_EVENT_LISTENER(target, "click", (event) => {{
      if (!event || event.isTrusted !== true) return;
      return handler(event);
    }});
  }}

  function renderMenu(anchor) {{
    const existingMenu = document.querySelector(MENU_SELECTOR);
    if (existingMenu) existingMenu.remove();
    const menu = document.createElement("div");
    menu.dataset.amazifyMenu = "true";
    const enabledCount = countMapValues(state.plugins, (plugin) => plugin.enabled);
    menu.innerHTML = `
      <div class="amazify-menu-head">
        <div class="amazify-menu-title">${{logoMarkup("amazify-logo amazify-logo-menu")}}<span>Amazify</span></div>
        <div class="amazify-menu-status">${{esc(enabledCount)}} active</div>
      </div>
      <div class="amazify-menu-body">
        <button class="amazify-menu-item" type="button" data-amazify-open="marketplace">
          <span>Marketplace</span><span>Plugins</span>
        </button>
        <button class="amazify-menu-item" type="button" data-amazify-open="settings">
          <span>Settings</span><span>Preferences</span>
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
    addTrustedLifecycleClick(menu.querySelector("[data-amazify-disable-all]"), async () => {{
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
    state.activePluginSettingsId = "";
    const existingMenu = document.querySelector(MENU_SELECTOR);
    if (existingMenu) existingMenu.remove();
    renderPanel();
    if (tab === "marketplace" && state.preferences.autoCheckUpdates) {{
      refreshCatalogFromBridge();
    }} else if (tab === "settings") {{
      refreshSettingsPanel();
    }}
  }}

  function closePanel() {{
    state.activePanel = null;
    state.activePluginSettingsId = "";
    cleanupRenderedSettingsSections();
    const existingPanel = document.querySelector(PANEL_SELECTOR);
    if (existingPanel) existingPanel.remove();
  }}

  function renderPanel() {{
    cleanupRenderedSettingsSections();
    const panel = ensurePanel();
    const active = state.activePanel || "marketplace";
    panel.innerHTML = `
      <div class="amazify-panel-header">
        <div class="amazify-panel-title">
          ${{logoMarkup("amazify-logo amazify-logo-panel")}}
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
        ${{active === "settings"
          ? renderSettings()
          : state.activePluginSettingsId
            ? renderPluginSettingsView(state.activePluginSettingsId)
            : renderMarketplace()}}
      </div>
    `;
    panel.querySelector(".amazify-close").addEventListener("click", closePanel);
    panel.querySelectorAll("[data-amazify-tab]").forEach((tab) => {{
      tab.addEventListener("click", () => {{
        state.activePanel = tab.dataset.amazifyTab;
        state.activePluginSettingsId = "";
        renderPanel();
        if (state.activePanel === "marketplace" && state.preferences.autoCheckUpdates) {{
          refreshCatalogFromBridge();
        }} else if (state.activePanel === "settings") {{
          refreshSettingsPanel();
        }}
      }});
    }});
    panel.querySelectorAll("[data-amazify-toggle-plugin]").forEach((toggle) => {{
      addTrustedLifecycleClick(toggle, async () => {{
        const pluginId = toggle.dataset.amazifyTogglePlugin;
        const enabled = toggle.getAttribute("aria-pressed") !== "true";
        await setPluginEnabled(pluginId, enabled);
      }});
    }});
    const refreshStateButton = panel.querySelector("[data-amazify-refresh-state]");
    if (refreshStateButton) addTrustedLifecycleClick(refreshStateButton, refreshFromBridge);
    const refreshCatalogButton = panel.querySelector("[data-amazify-refresh-catalog]");
    if (refreshCatalogButton) addTrustedLifecycleClick(refreshCatalogButton, refreshCatalogFromBridge);
    const checkAppUpdateButton = panel.querySelector("[data-amazify-check-app-update]");
    if (checkAppUpdateButton) addTrustedLifecycleClick(checkAppUpdateButton, startApplicationUpdateCheck);
    const installAppUpdateButton = panel.querySelector("[data-amazify-install-app-update]");
    if (installAppUpdateButton) addTrustedLifecycleClick(installAppUpdateButton, installApplicationUpdate);
    const openMarketplaceButton = panel.querySelector("[data-amazify-open-marketplace]");
    if (openMarketplaceButton) openMarketplaceButton.addEventListener("click", () => openPanel("marketplace"));
    panel.querySelectorAll("[data-amazify-setting]").forEach((toggle) => {{
      toggle.addEventListener("click", () => {{
        const name = toggle.dataset.amazifySetting;
        const enabled = toggle.getAttribute("aria-pressed") !== "true";
        setRuntimePreference(name, enabled);
      }});
    }});
    const disableAllButton = panel.querySelector("[data-amazify-disable-all]");
    if (disableAllButton) addTrustedLifecycleClick(disableAllButton, disableAllPlugins);
    panel.querySelectorAll("[data-amazify-install-plugin]").forEach((button) => {{
      addTrustedLifecycleClick(button, async () => {{
        await installPlugin(button.dataset.amazifyInstallPlugin);
      }});
    }});
    panel.querySelectorAll("[data-amazify-open-plugin-settings]").forEach((button) => {{
      button.addEventListener("click", () => openPluginSettings(button.dataset.amazifyOpenPluginSettings));
    }});
    const pluginSettingsBack = panel.querySelector("[data-amazify-plugin-settings-back]");
    if (pluginSettingsBack) pluginSettingsBack.addEventListener("click", () => {{
      state.activePluginSettingsId = "";
      renderPanel();
    }});
    const resetPluginSettingsButton = panel.querySelector("[data-amazify-reset-plugin-settings]");
    if (resetPluginSettingsButton) addTrustedLifecycleClick(resetPluginSettingsButton, () => {{
      try {{
        resetPluginSettings(resetPluginSettingsButton.dataset.amazifyResetPluginSettings);
        state.lastError = "";
      }} catch (error) {{
        state.lastError = error.message || NATIVE_STRING(error);
      }}
      renderPanel();
    }});
    bindPluginSettingControls(panel);
    if (active === "marketplace" && state.activePluginSettingsId) {{
      renderPluginSettingsSections(panel, state.activePluginSettingsId);
    }}
  }}

  function openPluginSettings(pluginId) {{
    if (!pluginId || !manifestForPlugin(pluginId)) return;
    state.activePanel = "marketplace";
    state.activePluginSettingsId = pluginId;
    renderPanel();
  }}

  function cleanupRenderedSettingsSections(pluginId = "") {{
    const keys = mapKeysSnapshot(state.settingsRenderCleanups);
    for (let index = 0; index < keys.length; index += 1) {{
      const key = keys[index];
      if (pluginId && !key.startsWith(`${{pluginId}}:`)) continue;
      const cleanup = NATIVE_MAP_GET(state.settingsRenderCleanups, key);
      NATIVE_MAP_DELETE(state.settingsRenderCleanups, key);
      if (typeof cleanup === "function") {{
        try {{ cleanup(); }} catch (error) {{
          console.warn("[Amazify] Plugin settings cleanup failed", key, error);
        }}
      }}
    }}
  }}

  function renderPluginSettingsSections(panel, pluginId) {{
    const body = panel ? panel.querySelector("[data-amazify-custom-settings-host]") : null;
    if (!body || !pluginId) return;
    const sections = mapValuesSnapshot(state.settingsSections);
    for (let index = 0; index < sections.length; index += 1) {{
      const section = sections[index];
      if (section.pluginId !== pluginId) continue;
      const wrapper = document.createElement("section");
      wrapper.className = "amazify-plugin-settings-section";
      wrapper.dataset.amazifyPluginId = section.pluginId;
      wrapper.innerHTML = `<div class="amazify-section-title">${{esc(section.title)}}</div>`;
      const host = document.createElement("div");
      host.className = "amazify-plugin-settings-host";
      wrapper.appendChild(host);
      body.appendChild(wrapper);
      try {{
        const cleanup = section.render(host);
        if (typeof cleanup === "function") {{
          NATIVE_MAP_SET(state.settingsRenderCleanups, section.key, cleanup);
        }}
      }} catch (error) {{
        host.textContent = `Unable to render ${{section.title}} settings.`;
        console.warn("[Amazify] Plugin settings render failed", section.pluginId, error);
      }}
    }}
  }}

  function renderMarketplace() {{
    const plugins = marketplacePlugins();
    if (!plugins.length) {{
      return '<div class="amazify-empty">No marketplace plugins were found. Check the catalog URL in settings or try refresh.</div>';
    }}
    const themes = [];
    const extensions = [];
    for (let index = 0; index < plugins.length; index += 1) {{
      const manifest = (plugins[index].installed || plugins[index].catalog).manifest;
      (manifest.type === "theme" ? themes : extensions).push(plugins[index]);
    }}
    return `
      ${{state.catalogError ? `<div class="amazify-error">${{esc(state.catalogError)}}</div>` : ""}}
      ${{themes.length ? `<section class="amazify-marketplace-section"><div class="amazify-section-title">Themes</div>${{themes.map(renderPluginRow).join("")}}</section>` : ""}}
      ${{extensions.length ? `<section class="amazify-marketplace-section"><div class="amazify-section-title">Plugins</div>${{extensions.map(renderPluginRow).join("")}}</section>` : ""}}
    `;
  }}

  function marketplacePluginForId(pluginId) {{
    const plugins = marketplacePlugins();
    for (let index = 0; index < plugins.length; index += 1) {{
      const manifest = (plugins[index].installed || plugins[index].catalog).manifest;
      if (manifest.id === pluginId) return plugins[index];
    }}
    return null;
  }}

  function hasCustomPluginSettings(pluginId) {{
    const sections = mapValuesSnapshot(state.settingsSections);
    for (let index = 0; index < sections.length; index += 1) {{
      if (sections[index].pluginId === pluginId) return true;
    }}
    return false;
  }}

  function renderPluginSettingControl(pluginId, manifest, definition) {{
    const settingId = NATIVE_STRING(definition.id || "");
    const type = NATIVE_STRING(definition.type || "");
    const value = pluginSettingValue(pluginId, manifest, settingId);
    const label = esc(definition.label || settingId);
    const description = definition.description
      ? `<span>${{esc(definition.description)}}</span>`
      : "";
    let control = "";
    if (type === "boolean") {{
      control = `<button class="amazify-toggle" type="button" aria-label="${{label}}" aria-pressed="${{value ? "true" : "false"}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="boolean"></button>`;
    }} else if (type === "color") {{
      control = `<label class="amazify-color-setting"><input type="color" value="${{esc(value)}}" aria-label="${{label}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="color"><code data-amazify-setting-output>${{esc(value)}}</code></label>`;
    }} else if (type === "image") {{
      const accepted = NATIVE_ARRAY_IS_ARRAY(definition.accept) ? definition.accept.join(",") : "image/png,image/jpeg,image/webp";
      const preview = value
        ? `<img class="amazify-image-setting-preview" src="${{esc(value)}}" alt="" aria-hidden="true">`
        : '<span class="amazify-image-setting-empty">No image</span>';
      control = `<div class="amazify-image-setting">${{preview}}<label class="amazify-quiet amazify-image-setting-choose">Choose image<input type="file" accept="${{esc(accepted)}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="image"></label>${{value ? `<button class="amazify-quiet" type="button" data-amazify-clear-image-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}">Remove</button>` : ""}}</div>`;
    }} else if (type === "range") {{
      control = `<label class="amazify-range-setting"><input type="range" min="${{esc(definition.min)}}" max="${{esc(definition.max)}}" step="${{esc(definition.step)}}" value="${{esc(value)}}" aria-label="${{label}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="range"><output data-amazify-setting-output>${{esc(value)}}</output></label>`;
    }} else if (type === "select") {{
      const options = NATIVE_ARRAY_IS_ARRAY(definition.options) ? definition.options : [];
      control = `<select class="amazify-select-setting" aria-label="${{label}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="select">${{options.map((option) => `<option value="${{esc(option.value)}}" ${{NATIVE_STRING(option.value) === NATIVE_STRING(value) ? "selected" : ""}}>${{esc(option.label)}}</option>`).join("")}}</select>`;
    }} else if (type === "text") {{
      control = `<input class="amazify-text-setting" type="text" value="${{esc(value)}}" maxlength="${{esc(definition.maxLength || 256)}}" placeholder="${{esc(definition.placeholder || "")}}" aria-label="${{label}}" data-amazify-plugin-setting="${{esc(pluginId)}}" data-amazify-plugin-setting-id="${{esc(settingId)}}" data-amazify-plugin-setting-type="text">`;
    }}
    return `<div class="amazify-plugin-setting-field"><div><strong>${{label}}</strong>${{description}}</div><div class="amazify-plugin-setting-control">${{control}}</div></div>`;
  }}

  function renderPluginSettingsView(pluginId) {{
    const plugin = marketplacePluginForId(pluginId);
    if (!plugin) return '<div class="amazify-empty">This plugin is no longer available.</div>';
    const installed = plugin.installed;
    const catalog = plugin.catalog;
    const manifest = (installed || catalog).manifest;
    const definitions = manifestSettings(manifest);
    const customSettings = hasCustomPluginSettings(pluginId);
    const canInstall = Boolean(catalog && catalog.compatible !== false);
    const installLabel = catalog && installed && catalog.updateAvailable
      ? `Update to v${{esc(catalog.latestVersion || catalog.manifest.version)}}`
      : "Reinstall plugin";
    const installAction = catalog
      ? `<button class="amazify-primary" type="button" data-amazify-install-plugin="${{esc(pluginId)}}" ${{canInstall ? "" : "disabled"}}>${{installLabel}}</button>`
      : '<span class="amazify-plugin-settings-note">Local plugins cannot be reinstalled from the catalog.</span>';
    const settingsMarkup = definitions.length
      ? definitions.map((definition) => renderPluginSettingControl(pluginId, manifest, definition)).join("")
      : customSettings
        ? ""
        : '<div class="amazify-empty">This plugin has no configurable features.</div>';
    return `
      <div class="amazify-plugin-settings-view">
        <button class="amazify-back-button" type="button" data-amazify-plugin-settings-back>&larr; Marketplace</button>
        <div class="amazify-plugin-settings-heading">
          <div><div class="amazify-plugin-name">${{esc(manifest.name)}}</div><div class="amazify-plugin-meta">${{esc(manifest.type)}} by ${{esc(manifest.author)}} - v${{esc(installed ? installed.manifest.version : manifest.version)}}</div></div>
        </div>
        <div class="amazify-plugin-desc">${{esc(manifest.description)}}</div>
        <div class="amazify-section-title">Plugin settings</div>
        <div class="amazify-plugin-settings-fields">${{settingsMarkup}}</div>
        <div data-amazify-custom-settings-host></div>
        <div class="amazify-plugin-settings-actions">
          ${{definitions.length ? `<button class="amazify-quiet" type="button" data-amazify-reset-plugin-settings="${{esc(pluginId)}}">Reset defaults</button>` : ""}}
          ${{installAction}}
        </div>
      </div>
    `;
  }}

  function bindPluginSettingControls(panel) {{
    panel.querySelectorAll("[data-amazify-plugin-setting]").forEach((control) => {{
      const pluginId = control.dataset.amazifyPluginSetting;
      const settingId = control.dataset.amazifyPluginSettingId;
      const type = control.dataset.amazifyPluginSettingType;
      if (type === "image") {{
        control.addEventListener("change", (event) => {{
          if (!event || event.isTrusted !== true || !control.files || !control.files[0]) return;
          const manifest = manifestForPlugin(pluginId);
          const definition = pluginSettingDefinition(manifest, settingId);
          const file = control.files[0];
          const accepted = definition && NATIVE_ARRAY_IS_ARRAY(definition.accept) ? definition.accept : [];
          const maxBytes = definition ? Number(definition.maxBytes) : 0;
          if (!accepted.includes(file.type) || !Number.isFinite(maxBytes) || file.size > maxBytes) {{
            state.lastError = "The selected image type or size is not allowed by this plugin.";
            renderPanel();
            return;
          }}
          if (!NATIVE_FILE_READER || !NATIVE_FILE_READER_READ_AS_DATA_URL) {{
            state.lastError = "Image selection is unavailable in this Amazon Music build.";
            renderPanel();
            return;
          }}
          const reader = new NATIVE_FILE_READER();
          NATIVE_ADD_EVENT_LISTENER(reader, "load", () => {{
            try {{
              setPluginSetting(pluginId, settingId, NATIVE_STRING(reader.result || ""));
              state.lastError = "";
            }} catch (error) {{
              state.lastError = error.message || NATIVE_STRING(error);
            }}
            renderPanel();
          }});
          NATIVE_ADD_EVENT_LISTENER(reader, "error", () => {{
            state.lastError = "The selected image could not be read.";
            renderPanel();
          }});
          NATIVE_FILE_READER_READ_AS_DATA_URL(reader, file);
        }});
        return;
      }}
      const update = (event) => {{
        if (!event || event.isTrusted !== true) return;
        try {{
          const rawValue = type === "boolean"
            ? control.getAttribute("aria-pressed") !== "true"
            : control.value;
          const value = setPluginSetting(pluginId, settingId, rawValue);
          if (type === "boolean") control.setAttribute("aria-pressed", value ? "true" : "false");
          const output = control.parentElement && control.parentElement.querySelector("[data-amazify-setting-output]");
          if (output) output.textContent = NATIVE_STRING(value);
        }} catch (error) {{
          state.lastError = error.message || NATIVE_STRING(error);
        }}
      }};
      if (type === "boolean") addTrustedLifecycleClick(control, update);
      else control.addEventListener(type === "text" || type === "select" ? "change" : "input", update);
    }});
    panel.querySelectorAll("[data-amazify-clear-image-setting]").forEach((button) => {{
      addTrustedLifecycleClick(button, () => {{
        try {{
          setPluginSetting(
            button.dataset.amazifyClearImageSetting,
            button.dataset.amazifyPluginSettingId,
            ""
          );
          state.lastError = "";
        }} catch (error) {{
          state.lastError = error.message || NATIVE_STRING(error);
        }}
        renderPanel();
      }});
    }});
  }}

  function marketplacePlugins() {{
    const merged = new NATIVE_MAP();
    const catalogPlugins = mapValuesSnapshot(state.catalogPlugins);
    for (let index = 0; index < catalogPlugins.length; index += 1) {{
      const catalogPlugin = catalogPlugins[index];
      if (!catalogPlugin || !catalogPlugin.manifest || !catalogPlugin.manifest.id) continue;
      NATIVE_MAP_SET(merged, catalogPlugin.manifest.id, {{
        catalog: catalogPlugin,
        installed: NATIVE_MAP_GET(state.plugins, catalogPlugin.manifest.id) || null
      }});
    }}
    const installedPlugins = mapValuesSnapshot(state.plugins);
    for (let index = 0; index < installedPlugins.length; index += 1) {{
      const installed = installedPlugins[index];
      if (!installed || !installed.manifest || !installed.manifest.id) continue;
      if (!NATIVE_MAP_HAS(merged, installed.manifest.id)) {{
        NATIVE_MAP_SET(merged, installed.manifest.id, {{
          catalog: null,
          installed
        }});
      }}
    }}
    return mapValuesSnapshot(merged).sort((a, b) => {{
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
    const installedSecurity = installed && installed.security && typeof installed.security === "object"
      ? installed.security
      : null;
    const channel = catalog
      ? String(catalog.trust || catalog.channel || "community")
      : String((installedSecurity && installedSecurity.trust) || "local");
    const metaVersion = isInstalled ? installed.manifest.version : manifest.version;
    const permissions = (manifest.permissions || []).map((permission) => `<span class="amazify-permission">${{esc(permission)}}</span>`).join("");
    const sourceCommit = catalog ? String(catalog.sourceCommit || "") : String((installedSecurity && installedSecurity.sourceCommit) || "");
    const verificationRequired = Boolean(
      catalog && catalog.verification && catalog.verification.required
    );
    const installedVerified = Boolean(installedSecurity && installedSecurity.verified);
    const integrityFailed = Boolean(
      installedSecurity &&
      ["catalog-sha256", "bundled"].includes(String(installedSecurity.method || "")) &&
      installedSecurity.verified !== true
    );
    const incompatible = Boolean(
      (catalog && catalog.compatible === false) ||
      (installed && installed.compatible === false)
    );
    const compatibilityDetail = incompatible
      ? ` - requires Amazify ${{esc(manifest.minimumAmazifyVersion || (catalog && catalog.minimumAmazifyVersion) || "newer")}}`
      : "";
    const trustDetail = channel === "community"
      ? "Third-party community code - review its source and permissions before enabling"
      : channel === "stock"
        ? "Amazify stock plugin with pinned source and SHA-256 verification"
        : "Local plugin - source integrity is managed by you";
    const actionButton = isInstalled
      ? `<button class="amazify-quiet" type="button" data-amazify-open-plugin-settings="${{esc(manifest.id)}}">Settings</button>`
      : catalog
        ? `<button class="amazify-primary" type="button" data-amazify-install-plugin="${{esc(manifest.id)}}" ${{incompatible ? "disabled" : ""}}>Download</button>`
        : "";
    const toggleButton = isInstalled
      ? `<button class="amazify-toggle" type="button" aria-label="Toggle ${{esc(manifest.name)}}" aria-pressed="${{installed.enabled ? "true" : "false"}}" data-amazify-toggle-plugin="${{esc(manifest.id)}}" ${{integrityFailed || incompatible ? "disabled" : ""}}></button>`
      : "";
    return `
      <div class="amazify-plugin-row" data-amazify-plugin-id="${{esc(manifest.id)}}">
        <div class="amazify-plugin-top">
          <div>
            <div class="amazify-plugin-name">${{esc(manifest.name)}}</div>
            <div class="amazify-plugin-meta">${{esc(channel)}} ${{esc(manifest.type)}} by ${{esc(manifest.author)}} - v${{esc(metaVersion)}}${{isInstalled ? " installed" : ""}}${{catalog && isInstalled && catalog.updateAvailable ? ` - update ${{esc(catalog.latestVersion || catalog.manifest.version)}} available` : ""}}</div>
          </div>
          <div class="amazify-plugin-controls">${{actionButton}}${{toggleButton}}</div>
        </div>
        <div class="amazify-plugin-desc">${{esc(manifest.description)}}</div>
        <div class="amazify-plugin-meta">${{esc(trustDetail)}}${{sourceCommit ? ` - source ${{esc(sourceCommit.slice(0, 12))}}` : ""}}${{installedVerified ? " - installed files verified" : (!isInstalled && verificationRequired ? " - SHA-256 verification required" : "")}}${{integrityFailed ? " - integrity check failed; execution blocked" : ""}}${{compatibilityDetail}}</div>
        <div class="amazify-permissions">${{permissions || '<span class="amazify-permission">no special permissions</span>'}}</div>
      </div>
    `;
  }}

  function renderSettings() {{
    const pluginCount = mapValuesSnapshot(state.plugins).length;
    const catalogCount = mapValuesSnapshot(state.catalogPlugins).length;
    const enabledCount = countMapValues(state.plugins, (plugin) => plugin.enabled);
    const updateCount = countMapValues(state.catalogPlugins, (plugin) => plugin.updateAvailable);
    const appUpdate = state.appUpdate || {{}};
    const appUpdateStatus = String(appUpdate.status || "idle");
    const currentAppVersion = String(appUpdate.currentVersion || VERSION);
    const latestAppVersion = String(appUpdate.latestVersion || "");
    const appUpdateProgress = Math.min(100, Math.max(0, Number(appUpdate.progress || 0)));
    let appUpdateDetail = "Not checked yet";
    let appUpdateAction = '<button class="amazify-quiet" type="button" data-amazify-check-app-update>Check now</button>';
    if (appUpdateStatus === "checking") {{
      appUpdateDetail = "Checking the latest final GitHub release";
      appUpdateAction = '<button class="amazify-quiet" type="button" disabled>Checking</button>';
    }} else if (appUpdateStatus === "available") {{
      appUpdateDetail = `Amazify v${{latestAppVersion}} is available`;
      appUpdateAction = `<button class="amazify-primary" type="button" data-amazify-install-app-update>Install v${{esc(latestAppVersion)}}</button>`;
    }} else if (appUpdateStatus === "up-to-date") {{
      appUpdateDetail = `Amazify v${{currentAppVersion}} is up to date`;
    }} else if (appUpdateStatus === "downloading") {{
      appUpdateDetail = `Downloading and verifying installer - ${{appUpdateProgress}}%`;
      appUpdateAction = `<button class="amazify-primary" type="button" disabled>${{appUpdateProgress}}%</button>`;
    }} else if (appUpdateStatus === "launching") {{
      appUpdateDetail = "Starting the verified installer";
      appUpdateAction = '<button class="amazify-primary" type="button" disabled>Starting</button>';
    }} else if (appUpdateStatus === "launched") {{
      appUpdateDetail = "Installer launched - complete it to finish updating";
      appUpdateAction = '<button class="amazify-primary" type="button" disabled>Launched</button>';
    }} else if (appUpdateStatus === "error") {{
      appUpdateDetail = String(appUpdate.error || "Update check failed");
      appUpdateAction = '<button class="amazify-quiet" type="button" data-amazify-check-app-update>Try again</button>';
    }}
    const catalogStatus = state.catalogError
      ? state.catalogError
      : `${{catalogCount}} ${{catalogCount === 1 ? "entry" : "entries"}} loaded`;
    return `
      <div class="amazify-section-title">Preferences</div>
      <div class="amazify-setting-row">
        <div><strong>Check for plugin updates automatically</strong><span>Refresh the catalog whenever Marketplace opens</span></div>
        <button class="amazify-toggle" type="button" aria-label="Check for plugin updates automatically" aria-pressed="${{state.preferences.autoCheckUpdates ? "true" : "false"}}" data-amazify-setting="autoCheckUpdates"></button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Check for Amazify updates automatically</strong><span>Check when Settings opens</span></div>
        <button class="amazify-toggle" type="button" aria-label="Check for Amazify updates automatically" aria-pressed="${{state.preferences.autoCheckAppUpdates ? "true" : "false"}}" data-amazify-setting="autoCheckAppUpdates"></button>
      </div>

      <div class="amazify-section-title">Application updates</div>
      <div class="amazify-setting-row">
        <div><strong>Amazify v${{esc(currentAppVersion)}}</strong><span>${{esc(appUpdateDetail)}}</span></div>
        ${{appUpdateAction}}
      </div>

      <div class="amazify-section-title">Plugin management</div>
      <div class="amazify-setting-row">
        <div><strong>Installed plugins</strong><span>${{esc(enabledCount)}} enabled from ${{esc(pluginCount)}} installed</span></div>
        <button class="amazify-quiet" type="button" data-amazify-open-marketplace>Manage</button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Available updates</strong><span>${{esc(updateCount)}} plugin ${{updateCount === 1 ? "update" : "updates"}} found</span></div>
        <button class="amazify-primary" type="button" data-amazify-refresh-catalog>Check now</button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Disable all plugins</strong><span>Turn off every installed plugin without uninstalling it</span></div>
        <button class="amazify-danger" type="button" data-amazify-disable-all ${{enabledCount ? "" : "disabled"}}>Disable all</button>
      </div>

      <div class="amazify-section-title">Runtime</div>
      <div class="amazify-setting-row">
        <div><strong>Connection</strong><span>${{esc(state.bridgeStatus)}} at ${{esc(BRIDGE_URL)}}</span></div>
        <button class="amazify-quiet" type="button" data-amazify-refresh-state>Refresh</button>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Catalog</strong><span>${{esc(catalogStatus)}}</span></div>
        <span class="amazify-runtime-badge">${{esc(updateCount)}} updates</span>
      </div>
      <div class="amazify-setting-row">
        <div><strong>Catalog source</strong><span class="amazify-setting-value" title="${{esc(state.catalogUrl || "Not loaded")}}">${{esc(state.catalogUrl || "Not loaded")}}</span></div>
        <span class="amazify-runtime-badge">v${{esc(VERSION)}}</span>
      </div>
    `;
  }}

  function setRuntimePreference(name, value) {{
    if (!NATIVE_HAS_OWN(state.preferences, name)) return;
    state.preferences[name] = Boolean(value);
    try {{
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, NATIVE_JSON_STRINGIFY(state.preferences));
    }} catch (_error) {{
      // The setting still applies for this session when storage is unavailable.
    }}
    renderPanel();
    if (name === "autoCheckAppUpdates" && state.preferences.autoCheckAppUpdates) {{
      startApplicationUpdateCheck();
    }}
  }}

  class BridgeResponseError extends Error {{}}

  async function fetchBridge(path, options = {{}}) {{
    if (!NATIVE_FETCH || !NATIVE_RESPONSE_JSON) {{
      throw new TypeError("Native fetch is unavailable");
    }}
    const response = await NATIVE_FETCH(`${{BRIDGE_URL}}${{path}}`, {{
      ...options,
      headers: {{
        "Content-Type": "application/json",
        "X-Amazify-Token": BRIDGE_TOKEN,
        ...(options.headers || {{}})
      }}
    }});
    const data = await NATIVE_RESPONSE_JSON(response);
    if (!response.ok || data.error) {{
      throw new BridgeResponseError(data.error || `Bridge request failed: ${{response.status}}`);
    }}
    return data;
  }}

  function nativeCommand(name, payload = {{}}, timeoutMs = 5000) {{
    return new NATIVE_PROMISE((resolve, reject) => {{
      if (!NATIVE_COMMAND || !NATIVE_SESSION_NONCE || !NATIVE_RESPONSE_CALLBACK) {{
        reject(new Error("Local bridge unavailable"));
        return;
      }}
      const id = `${{NATIVE_SESSION_NONCE}}.${{Date.now()}}.${{++state.nativeSequence}}`;
      const timeout = NATIVE_SET_TIMEOUT(() => {{
        NATIVE_MAP_DELETE(state.nativeRequests, id);
        reject(new Error("Native bridge timed out"));
      }}, Math.max(1000, Math.min(30000, Number(timeoutMs) || 5000)));
      NATIVE_MAP_SET(state.nativeRequests, id, {{ resolve, reject, timeout }});
      NATIVE_COMMAND(NATIVE_JSON_STRINGIFY({{
        id,
        name,
        payload,
        sessionNonce: NATIVE_SESSION_NONCE
      }}));
    }});
  }}

  function receiveNativeResult(id, result) {{
    const request = NATIVE_MAP_GET(state.nativeRequests, id);
    if (!request) return false;
    NATIVE_CLEAR_TIMEOUT(request.timeout);
    NATIVE_MAP_DELETE(state.nativeRequests, id);
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
          body: NATIVE_JSON_STRINGIFY({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "plugins.disable") {{
        return await fetchBridge("/plugins/disable", {{
          method: "POST",
          body: NATIVE_JSON_STRINGIFY({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "plugins.install") {{
        return await fetchBridge("/plugins/install", {{
          method: "POST",
          body: NATIVE_JSON_STRINGIFY({{ pluginId: payload.pluginId }})
        }});
      }}
      if (name === "catalog.refresh") {{
        return await fetchBridge("/command", {{
          method: "POST",
          body: NATIVE_JSON_STRINGIFY({{ name, payload }})
        }});
      }}
      return await fetchBridge("/command", {{
        method: "POST",
        body: NATIVE_JSON_STRINGIFY({{ name, payload }})
      }});
    }} catch (error) {{
      if (error instanceof BridgeResponseError) {{
        throw error;
      }}
      const result = await nativeCommand(name, payload);
      state.bridgeStatus = "Connected through DevTools binding";
      return result;
    }}
  }}

  function syncApplicationUpdate(update) {{
    if (!update || typeof update !== "object") return;
    state.appUpdate = NATIVE_ASSIGN({{}}, update);
    if (state.activePanel === "settings") {{
      renderPanel();
    }}
  }}

  function appUpdateNeedsPolling() {{
    const status = String((state.appUpdate && state.appUpdate.status) || "");
    return status === "checking" || status === "downloading" || status === "launching";
  }}

  function scheduleApplicationUpdatePoll() {{
    if (state.appUpdatePollTimer !== null) {{
      NATIVE_CLEAR_TIMEOUT(state.appUpdatePollTimer);
      state.appUpdatePollTimer = null;
    }}
    if (!runtimeActive || state.activePanel !== "settings" || !appUpdateNeedsPolling()) return;
    state.appUpdatePollTimer = NATIVE_SET_TIMEOUT(() => {{
      state.appUpdatePollTimer = null;
      refreshApplicationUpdateStatus();
    }}, 750);
  }}

  async function refreshApplicationUpdateStatus() {{
    try {{
      const result = await nativeCommand("app.update.status", {{}});
      if (result && result.appUpdate) syncApplicationUpdate(result.appUpdate);
    }} catch (error) {{
      syncApplicationUpdate({{
        ...(state.appUpdate || {{}}),
        status: "error",
        error: error.message || String(error)
      }});
    }} finally {{
      scheduleApplicationUpdatePoll();
    }}
  }}

  async function refreshSettingsPanel() {{
    await refreshFromBridge();
    if (!runtimeActive || state.activePanel !== "settings") return;
    if (state.preferences.autoCheckAppUpdates) {{
      await startApplicationUpdateCheck();
    }} else {{
      await refreshApplicationUpdateStatus();
    }}
  }}

  async function startApplicationUpdateCheck() {{
    try {{
      const result = await nativeCommand("app.update.check", {{}});
      if (result && result.appUpdate) syncApplicationUpdate(result.appUpdate);
    }} catch (error) {{
      syncApplicationUpdate({{
        ...(state.appUpdate || {{}}),
        status: "error",
        error: error.message || String(error)
      }});
    }} finally {{
      scheduleApplicationUpdatePoll();
    }}
  }}

  async function installApplicationUpdate() {{
    const update = state.appUpdate || {{}};
    const latestVersion = String(update.latestVersion || "");
    if (!update.updateAvailable || !latestVersion) return;
    const confirmed = NATIVE_CONFIRM(
      `Install Amazify v${{latestVersion}}?\n\n` +
      "Amazify will download the official GitHub release installer, verify its SHA-256 digest, and open the installer. " +
      "The background daemon will restart during installation."
    );
    if (!confirmed) return;
    try {{
      const result = await nativeCommand("app.update.install", {{}});
      if (result && result.appUpdate) syncApplicationUpdate(result.appUpdate);
    }} catch (error) {{
      syncApplicationUpdate({{
        ...(state.appUpdate || {{}}),
        status: "error",
        error: error.message || String(error)
      }});
    }} finally {{
      scheduleApplicationUpdatePoll();
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
      const data = await bridgeCommand("plugins.disableAll", {{}});
      state.lastError = "";
      syncStatePayload(data);
    }} catch (error) {{
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  async function installPlugin(pluginId) {{
    if (!pluginId) return;
    const catalog = NATIVE_MAP_GET(state.catalogPlugins, pluginId);
    if (!catalog || !catalog.manifest) {{
      state.lastError = "The selected plugin is not present in the verified catalog.";
      renderPanel();
      return;
    }}
    const manifest = catalog.manifest;
    const trust = String(catalog.trust || catalog.channel || "community");
    const permissions = Array.isArray(manifest.permissions) && manifest.permissions.length
      ? manifest.permissions.join(", ")
      : "none declared";
    const source = `${{String(catalog.repository || "unknown source")}}@${{String(catalog.sourceCommit || "").slice(0, 12)}}`;
    const warning = trust === "community"
      ? "This is third-party community code. Review its source before enabling it."
      : "This is an Amazify stock plugin from a pinned source revision.";
    const installed = NATIVE_MAP_HAS(state.plugins, pluginId);
    const promptAction = installed
      ? (catalog.updateAvailable ? "Install this update" : "Reinstall this plugin")
      : "Download this plugin";
    const confirmed = NATIVE_CONFIRM(
      `${{promptAction}}?\n\n` +
      `${{manifest.name}} v${{manifest.version}}\n` +
      `Trust: ${{trust}}\nSource: ${{source}}\nPermissions: ${{permissions}}\n\n` +
      `${{warning}}\n\nThe download is checked against its catalog SHA-256 hashes and will remain disabled until you enable it.`
    );
    if (!confirmed) return;
    try {{
      state.lastError = "";
      const data = await bridgeCommand("plugins.install", {{ pluginId }});
      syncStatePayload(data);
    }} catch (error) {{
      state.lastError = error.message || String(error);
      renderPanel();
    }}
  }}

  function normalizeAssetPath(input, basePath = "") {{
    let raw = String(input || "").trim().replace(/\\\\/g, "/");
    if (!raw || raw.startsWith("#") || raw.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(raw)) {{
      return "";
    }}
    try {{
      raw = decodeURIComponent(raw);
    }} catch (_error) {{
      // Keep the original value if it is not URL-encoded.
    }}
    const suffixStart = raw.search(/[?#]/);
    if (suffixStart >= 0) {{
      raw = raw.slice(0, suffixStart);
    }}
    const baseParts = basePath ? String(basePath).replace(/\\\\/g, "/").split("/").slice(0, -1) : [];
    const parts = [...baseParts, ...raw.split("/")];
    const normalized = [];
    for (const part of parts) {{
      if (!part || part === ".") continue;
      if (part === "..") {{
        if (!normalized.length) return "";
        normalized.pop();
        continue;
      }}
      normalized.push(part);
    }}
    return normalized.join("/");
  }}

  function publicAsset(asset) {{
    if (!asset) return null;
    return {{
      name: String(asset.name || ""),
      path: String(asset.path || ""),
      mimeType: String(asset.mimeType || "application/octet-stream"),
      size: Number(asset.size || 0),
      dataUri: String(asset.dataUri || "")
    }};
  }}

  function buildPluginAssetIndex(plugin) {{
    const index = new NATIVE_MAP();
    const assets = plugin && plugin.source && Array.isArray(plugin.source.assets) ? plugin.source.assets : [];
    for (const asset of assets) {{
      const normalized = publicAsset(asset);
      if (!normalized || !normalized.dataUri) continue;
      const keys = [
        normalized.name,
        normalized.path,
        normalizeAssetPath(normalized.name),
        normalizeAssetPath(normalized.path)
      ].filter(Boolean);
      for (const key of keys) {{
        NATIVE_MAP_SET(index, key, normalized);
      }}
    }}
    return index;
  }}

  function findAssetInIndex(assetIndex, reference, basePath = "") {{
    if (!assetIndex || !reference) return null;
    return (
      NATIVE_MAP_GET(assetIndex, NATIVE_STRING(reference)) ||
      NATIVE_MAP_GET(assetIndex, normalizeAssetPath(reference)) ||
      NATIVE_MAP_GET(assetIndex, normalizeAssetPath(reference, basePath)) ||
      null
    );
  }}

  function pluginAsset(pluginId, nameOrPath) {{
    const plugin = NATIVE_MAP_GET(state.plugins, pluginId);
    if (!plugin) return null;
    return findAssetInIndex(buildPluginAssetIndex(plugin), nameOrPath);
  }}

  function listPluginAssets(pluginId) {{
    const plugin = NATIVE_MAP_GET(state.plugins, pluginId);
    const assets = plugin && plugin.source && Array.isArray(plugin.source.assets) ? plugin.source.assets : [];
    return assets.map(publicAsset).filter(Boolean);
  }}

  function rewriteCssAssetUrls(css, stylePath, assetIndex) {{
    return String(css || "").replace(/url\\(\\s*(['"]?)([^'")]+)\\1\\s*\\)/g, (_match, _quote, rawReference) => {{
      const reference = String(rawReference || "").trim();
      const asset = findAssetInIndex(assetIndex, reference, stylePath);
      if (!asset) {{
        return _match;
      }}
      return 'url("' + String(asset.dataUri || "").replace(/"/g, '\\"') + '")';
    }});
  }}

  function clonePlain(value) {{
    if (NATIVE_ARRAY_IS_ARRAY(value)) {{
      const copy = [];
      for (let index = 0; index < value.length; index += 1) {{
        copy[index] = clonePlain(value[index]);
      }}
      return copy;
    }}
    if (!value || typeof value !== "object") return value;
    const copy = {{}};
    const keys = NATIVE_KEYS(value);
    for (let index = 0; index < keys.length; index += 1) {{
      const key = keys[index];
      copy[key] = clonePlain(value[key]);
    }}
    return copy;
  }}

  function freezeDeep(value) {{
    if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
    const keys = NATIVE_KEYS(value);
    for (let index = 0; index < keys.length; index += 1) {{
      freezeDeep(value[keys[index]]);
    }}
    return NATIVE_FREEZE(value);
  }}

  function declaredPermissions(manifest) {{
    const source = manifest && NATIVE_ARRAY_IS_ARRAY(manifest.permissions)
      ? manifest.permissions
      : [];
    const result = [];
    for (let index = 0; index < source.length; index += 1) {{
      if (typeof source[index] === "string") result[result.length] = source[index];
    }}
    return result;
  }}

  function declaresPermission(manifest, name) {{
    const permissions = declaredPermissions(manifest);
    for (let index = 0; index < permissions.length; index += 1) {{
      if (permissions[index] === name) return true;
    }}
    return false;
  }}

  function publicPluginRecord(plugin) {{
    if (!plugin || !plugin.manifest) return undefined;
    return freezeDeep({{
      manifest: clonePlain(plugin.manifest),
      enabled: Boolean(plugin.enabled),
      security: clonePlain(plugin.security || {{}})
    }});
  }}

  const publicPluginLookup = NATIVE_FREEZE({{
    get: (pluginId) => publicPluginRecord(NATIVE_MAP_GET(state.plugins, NATIVE_STRING(pluginId || "")))
  }});

  function scopedReference(pluginId, args) {{
    if (args.length >= 2) {{
      if (NATIVE_STRING(args[0] || "") !== pluginId) {{
        throw new Error("Plugins may only access their own assets");
      }}
      return args[1];
    }}
    return args[0];
  }}

  function addHeaderActionForPlugin(pluginId, args) {{
    let label;
    let onClick;
    if (args.length >= 3) {{
      if (NATIVE_STRING(args[0] || "") !== pluginId) {{
        throw new Error("Plugins may only register their own header actions");
      }}
      label = args[1];
      onClick = args[2];
    }} else {{
      label = args[0];
      onClick = args[1];
    }}
    attachRoot();
    const action = document.createElement("button");
    action.type = "button";
    action.className = "amazify-plugin-action";
    action.dataset.amazifyPluginId = pluginId;
    action.textContent = String(label || "Plugin");
    action.addEventListener("click", (event) => {{
      event.stopPropagation();
      if (typeof onClick === "function") onClick(event);
    }});
    state.actionHost.appendChild(action);
    return action;
  }}

  function addSettingsSectionForPlugin(pluginId, descriptor) {{
    if (!descriptor || typeof descriptor !== "object") {{
      throw new TypeError("Plugin settings section must be an object");
    }}
    const sectionId = NATIVE_STRING(descriptor.id || "").trim();
    const title = NATIVE_STRING(descriptor.title || "").trim();
    if (!/^[a-z0-9][a-z0-9._-]{{1,63}}$/.test(sectionId)) {{
      throw new Error("Plugin settings section id is invalid");
    }}
    if (!title || typeof descriptor.render !== "function") {{
      throw new Error("Plugin settings section requires a title and render function");
    }}
    const key = `${{pluginId}}:${{sectionId}}`;
    if (NATIVE_MAP_HAS(state.settingsSections, key)) {{
      throw new Error("Plugin settings section is already registered");
    }}
    const record = {{ key, pluginId, title, render: descriptor.render }};
    NATIVE_MAP_SET(state.settingsSections, key, record);
    if (state.activePluginSettingsId === pluginId) renderPanel();
    let active = true;
    return () => {{
      if (!active) return;
      active = false;
      cleanupRenderedSettingsSections(pluginId);
      NATIVE_MAP_DELETE(state.settingsSections, key);
      if (state.activePluginSettingsId === pluginId) renderPanel();
    }};
  }}

  function capabilityMajor(version) {{
    const match = /^(\\d+)(?:\\.|$)/.exec(NATIVE_STRING(version || ""));
    return match ? Number(match[1]) : -1;
  }}

  function capabilityForRequest(request) {{
    if (!request || typeof request !== "object") return null;
    const name = NATIVE_STRING(request.name || "");
    const providerId = NATIVE_STRING(request.providerId || "");
    const requiredMajor = Number(request.major);
    const record = NATIVE_MAP_GET(state.capabilityProviders, name);
    if (
      !record || !record.active || record.providerId !== providerId ||
      !Number.isInteger(requiredMajor) || record.major !== requiredMajor
    ) {{
      return null;
    }}
    return record.facade;
  }}

  function notifyCapabilitySubscribers(name) {{
    NATIVE_MAP_FOR_EACH(state.capabilitySubscribers, (records) => {{
      for (let index = 0; index < records.length; index += 1) {{
        const record = records[index];
        if (!record.active || record.request.name !== name) continue;
        try {{ record.callback(capabilityForRequest(record.request)); }} catch (error) {{
          console.warn("[Amazify] Capability subscriber failed", record.pluginId, error);
        }}
      }}
    }});
  }}

  function revokeCapabilityRecord(record) {{
    if (!record || !record.active) return;
    record.active = false;
    if (NATIVE_MAP_GET(state.capabilityProviders, record.name) === record) {{
      NATIVE_MAP_DELETE(state.capabilityProviders, record.name);
    }}
    notifyCapabilitySubscribers(record.name);
  }}

  function provideCapabilityForPlugin(pluginId, nameValue, definition) {{
    const name = NATIVE_STRING(nameValue || "");
    if (!/^[a-z0-9][a-z0-9._-]{{2,191}}$/.test(name) || !name.startsWith(`${{pluginId}}.`)) {{
      throw new Error("Capability names must be namespaced to the provider plugin");
    }}
    if (!definition || typeof definition !== "object" || !definition.api || typeof definition.api !== "object") {{
      throw new TypeError("Capability definition requires an api object");
    }}
    const version = NATIVE_STRING(definition.version || "");
    const major = capabilityMajor(version);
    if (major < 0) throw new Error("Capability version is invalid");
    const existing = NATIVE_MAP_GET(state.capabilityProviders, name);
    if (existing && existing.active) throw new Error("Capability is already provided");

    const record = {{ name, providerId: pluginId, version, major, active: true, facade: null }};
    const facade = {{ providerId: pluginId, name, version }};
    const apiKeys = NATIVE_KEYS(definition.api);
    for (let index = 0; index < apiKeys.length; index += 1) {{
      const key = apiKeys[index];
      const value = definition.api[key];
      if (typeof value !== "function") continue;
      facade[key] = (...args) => {{
        if (!record.active) throw new Error("Capability is unavailable");
        return value(...args);
      }};
    }}
    record.facade = NATIVE_FREEZE(facade);
    NATIVE_MAP_SET(state.capabilityProviders, name, record);
    notifyCapabilitySubscribers(name);
    return () => revokeCapabilityRecord(record);
  }}

  function subscribeCapabilityForPlugin(pluginId, request, callback) {{
    if (!request || typeof request !== "object" || typeof callback !== "function") {{
      throw new TypeError("Capability subscription requires a request and callback");
    }}
    const normalized = NATIVE_FREEZE({{
      name: NATIVE_STRING(request.name || ""),
      providerId: NATIVE_STRING(request.providerId || ""),
      major: Number(request.major)
    }});
    if (!normalized.name || !normalized.providerId || !Number.isInteger(normalized.major)) {{
      throw new Error("Capability subscription is invalid");
    }}
    const record = {{ pluginId, request: normalized, callback, active: true }};
    const records = NATIVE_MAP_GET(state.capabilitySubscribers, pluginId) || [];
    records[records.length] = record;
    NATIVE_MAP_SET(state.capabilitySubscribers, pluginId, records);
    callback(capabilityForRequest(normalized));
    return () => {{ record.active = false; }};
  }}

  function cleanupPluginRegistrations(pluginId) {{
    cleanupRenderedSettingsSections(pluginId);
    const sectionKeys = mapKeysSnapshot(state.settingsSections);
    for (let index = 0; index < sectionKeys.length; index += 1) {{
      const key = sectionKeys[index];
      const section = NATIVE_MAP_GET(state.settingsSections, key);
      if (section && section.pluginId === pluginId) NATIVE_MAP_DELETE(state.settingsSections, key);
    }}
    const subscriptions = NATIVE_MAP_GET(state.capabilitySubscribers, pluginId) || [];
    for (let index = 0; index < subscriptions.length; index += 1) subscriptions[index].active = false;
    NATIVE_MAP_DELETE(state.capabilitySubscribers, pluginId);
    const settingSubscribers = NATIVE_MAP_GET(state.pluginSettingSubscribers, pluginId) || [];
    for (let index = 0; index < settingSubscribers.length; index += 1) settingSubscribers[index].active = false;
    NATIVE_MAP_DELETE(state.pluginSettingSubscribers, pluginId);
    const capabilities = mapValuesSnapshot(state.capabilityProviders);
    for (let index = 0; index < capabilities.length; index += 1) {{
      if (capabilities[index].providerId === pluginId) revokeCapabilityRecord(capabilities[index]);
    }}
  }}

  function buildPluginApi(plugin) {{
    const manifest = plugin.manifest || {{}};
    const pluginId = NATIVE_STRING(manifest.id || "");
    const permissionList = declaredPermissions(manifest);
    const permissions = new NATIVE_SET();
    for (let index = 0; index < permissionList.length; index += 1) {{
      NATIVE_SET_ADD(permissions, permissionList[index]);
    }}
    const ui = NATIVE_FREEZE({{
      openMarketplace: () => openPanel("marketplace"),
      openSettings: () => openPanel("settings"),
      openPluginSettings: () => openPluginSettings(pluginId),
      closePanel,
      addHeaderAction: (...args) => addHeaderActionForPlugin(pluginId, args),
      addSettingsSection: (descriptor) => addSettingsSectionForPlugin(pluginId, descriptor)
    }});
    const assets = NATIVE_FREEZE({{
      list: (requestedId) => {{
        if (requestedId !== undefined && NATIVE_STRING(requestedId) !== pluginId) {{
          throw new Error("Plugins may only access their own assets");
        }}
        return freezeDeep(clonePlain(listPluginAssets(pluginId)));
      }},
      get: (...args) => freezeDeep(clonePlain(pluginAsset(pluginId, scopedReference(pluginId, args)))),
      url: (...args) => {{
        const asset = pluginAsset(pluginId, scopedReference(pluginId, args));
        return asset ? asset.dataUri : "";
      }}
    }});
    const settings = NATIVE_FREEZE({{
      get: (settingId) => pluginSettingValue(pluginId, manifest, NATIVE_STRING(settingId || "")),
      set: (settingId, value) => setPluginSetting(pluginId, NATIVE_STRING(settingId || ""), value),
      all: () => pluginSettingsSnapshot(pluginId, manifest),
      subscribe: (listener) => subscribePluginSettings(pluginId, listener),
      reset: () => resetPluginSettings(pluginId)
    }});
    const api = {{
      version: VERSION,
      permissions: NATIVE_FREEZE(permissionList),
      ui,
      assets,
      settings,
      capabilities: NATIVE_FREEZE({{
        provide: (name, definition) => provideCapabilityForPlugin(pluginId, name, definition),
        subscribe: (request, callback) => subscribeCapabilityForPlugin(pluginId, request, callback)
      }})
    }};
    if (pluginId === "amazify.karaoke-lyrics" && NATIVE_SET_HAS(permissions, "lyrics-provider")) {{
      const requireActivation = () => {{
        const activation = window.navigator && window.navigator.userActivation;
        if (activation && activation.isActive !== true) {{
          throw new Error("This action requires a user interaction");
        }}
      }};
      api.lyricsProvider = NATIVE_FREEZE({{
        status: () => nativeCommand("lyrics.provider.status", {{}}, 5000),
        beginAuth: () => {{ requireActivation(); return nativeCommand("lyrics.provider.beginAuth", {{}}, 5000); }},
        disconnect: () => {{ requireActivation(); return nativeCommand("lyrics.provider.disconnect", {{}}, 5000); }},
        load: (track, requestKey) => nativeCommand("lyrics.provider.load", {{ track: clonePlain(track || {{}}), requestKey: NATIVE_STRING(requestKey || "") }}, 30000),
        cancel: (requestKey) => nativeCommand("lyrics.provider.cancel", {{ requestKey: NATIVE_STRING(requestKey || "") }}, 5000),
        clearCache: () => {{ requireActivation(); return nativeCommand("lyrics.provider.clearCache", {{}}, 5000); }}
      }});
    }}
    if (
      NATIVE_SET_HAS(permissions, "bridge-state") ||
      NATIVE_SET_HAS(permissions, "bridge-command")
    ) {{
      const pluginBridge = {{}};
      if (NATIVE_SET_HAS(permissions, "bridge-state")) {{
        pluginBridge.getState = () => bridgeCommand("state.get", {{}});
      }}
      if (NATIVE_SET_HAS(permissions, "bridge-command")) {{
        pluginBridge.command = (name, payload = {{}}) => {{
          const commandName = NATIVE_STRING(name || "");
          if (commandName !== "catalog.refresh" && commandName !== "plugins.disableAll") {{
            throw new Error("Plugin bridge command is not allowed");
          }}
          return bridgeCommand(commandName, payload);
        }};
      }}
      api.bridge = NATIVE_FREEZE(pluginBridge);
    }}
    return NATIVE_FREEZE(api);
  }}

  function mountPlugin(plugin) {{
    const manifest = plugin.manifest;
    const pluginId = manifest.id;
    unmountPlugin(pluginId);

    const assetIndex = buildPluginAssetIndex(plugin);
    const styles = plugin.source && plugin.source.styles ? plugin.source.styles : [];
    let cleanup = null;
    try {{
      if (styles.length && !declaresPermission(manifest, "dom-style")) {{
        throw new Error("Plugin styles require the dom-style permission");
      }}
      for (const styleSource of styles) {{
        const style = document.createElement("style");
        style.dataset.amazifyStyleId = pluginId;
        style.dataset.amazifyPluginId = pluginId;
        style.textContent = rewriteCssAssetUrls(styleSource.content, styleSource.path, assetIndex);
        document.head.appendChild(style);
      }}

    const entry = plugin.source ? plugin.source.entry : "";
    if (entry) {{
      const runner = new NATIVE_FUNCTION("Amazify", "manifest", "source", `${{entry}}\\n//# sourceURL=amazify-plugin-${{pluginId}}.js`);
      const pluginSource = NATIVE_ASSIGN({{}}, clonePlain(plugin.source || {{}}), {{
        assets: clonePlain(listPluginAssets(pluginId)),
        assetUrl: (nameOrPath) => {{
          const asset = pluginAsset(pluginId, nameOrPath);
          return asset ? asset.dataUri : "";
        }},
        asset: (nameOrPath) => freezeDeep(clonePlain(pluginAsset(pluginId, nameOrPath)))
      }});
      freezeDeep(pluginSource);
      const result = runner(
        buildPluginApi(plugin),
        freezeDeep(clonePlain(manifest)),
        pluginSource
      );
      if (typeof result === "function") {{
        cleanup = result;
      }}
    }}
    }} catch (error) {{
      document.querySelectorAll(`[data-amazify-plugin-id="${{cssEscape(pluginId)}}"], [data-amazify-style-id="${{cssEscape(pluginId)}}"]`).forEach((node) => node.remove());
      throw error;
    }}

    NATIVE_MAP_SET(state.mountedPlugins, pluginId, {{ cleanup }});
  }}

  function unmountPlugin(pluginId) {{
    const mounted = NATIVE_MAP_GET(state.mountedPlugins, pluginId);
    if (mounted && typeof mounted.cleanup === "function") {{
      try {{
        mounted.cleanup();
      }} catch (error) {{
        console.warn("[Amazify] Plugin cleanup failed", pluginId, error);
      }}
    }}
    cleanupPluginRegistrations(pluginId);
    document.querySelectorAll(`[data-amazify-plugin-id="${{cssEscape(pluginId)}}"], [data-amazify-style-id="${{cssEscape(pluginId)}}"]`).forEach((node) => node.remove());
    NATIVE_MAP_DELETE(state.mountedPlugins, pluginId);
  }}

  function syncPlugins(pluginList) {{
    const incoming = new NATIVE_MAP();
    const plugins = NATIVE_ARRAY_IS_ARRAY(pluginList) ? pluginList : [];
    for (let index = 0; index < plugins.length; index += 1) {{
      const plugin = plugins[index];
      if (!plugin || !plugin.manifest || !plugin.manifest.id) continue;
      NATIVE_MAP_SET(incoming, plugin.manifest.id, plugin);
    }}
    const mountedPluginIds = mapKeysSnapshot(state.mountedPlugins);
    for (let index = 0; index < mountedPluginIds.length; index += 1) {{
      const pluginId = mountedPluginIds[index];
      const next = NATIVE_MAP_GET(incoming, pluginId);
      if (!next || !next.enabled) {{
        unmountPlugin(pluginId);
      }}
    }}
    state.plugins = incoming;
    NATIVE_MAP_FOR_EACH(incoming, (plugin) => {{
      if (plugin.enabled) {{
        try {{
          mountPlugin(plugin);
        }} catch (error) {{
          state.lastError = `${{plugin.manifest.name}} failed: ${{error.message || error}}`;
          console.warn("[Amazify] Plugin mount failed", plugin.manifest.id, error);
        }}
      }}
    }});
    attachRoot();
    if (state.activePanel) {{
      renderPanel();
    }}
  }}

  function syncCatalog(pluginList, error = "") {{
    const incoming = new NATIVE_MAP();
    const plugins = NATIVE_ARRAY_IS_ARRAY(pluginList) ? pluginList : [];
    for (let index = 0; index < plugins.length; index += 1) {{
      const plugin = plugins[index];
      if (!plugin || !plugin.manifest || !plugin.manifest.id) continue;
      NATIVE_MAP_SET(incoming, plugin.manifest.id, plugin);
    }}
    state.catalogPlugins = incoming;
    state.catalogError = error || "";
    if (state.activePanel) {{
      renderPanel();
    }}
  }}

  function syncStatePayload(data) {{
    if (data && data.appUpdate) {{
      syncApplicationUpdate(data.appUpdate);
    }}
    if (typeof data.catalogUrl === "string") {{
      state.catalogUrl = data.catalogUrl;
    }}
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

  const publicRuntime = NATIVE_FREEZE({{
    version: VERSION,
    plugins: publicPluginLookup
  }});

  function cleanupRuntime() {{
    if (!runtimeActive) return;
    runtimeActive = false;
    NATIVE_REMOVE_EVENT_LISTENER(window, CLEANUP_EVENT, cleanupRuntime);
    if (state.observer) {{
      state.observer.disconnect();
      state.observer = null;
    }}
    if (state.appUpdatePollTimer !== null) {{
      NATIVE_CLEAR_TIMEOUT(state.appUpdatePollTimer);
      state.appUpdatePollTimer = null;
    }}
    const nativeRequests = mapValuesSnapshot(state.nativeRequests);
    for (let index = 0; index < nativeRequests.length; index += 1) {{
      const request = nativeRequests[index];
      NATIVE_CLEAR_TIMEOUT(request.timeout);
      request.reject(new Error("Amazify runtime stopped"));
    }}
    NATIVE_MAP_CLEAR(state.nativeRequests);
    const mountedPluginIds = mapKeysSnapshot(state.mountedPlugins);
    for (let index = 0; index < mountedPluginIds.length; index += 1) {{
      unmountPlugin(mountedPluginIds[index]);
    }}
    removeRuntimeSurfaces();
    const runtimeStyle = document.getElementById(RUNTIME_STYLE_ID);
    if (runtimeStyle) runtimeStyle.remove();
    document.removeEventListener("click", closeMenuOnOutsideClick, true);
    if (window.Amazify === publicRuntime) {{
      delete window.Amazify;
    }}
  }}

  NATIVE_ADD_EVENT_LISTENER(window, CLEANUP_EVENT, cleanupRuntime);
  try {{ delete window.Amazify; }} catch (_error) {{}}
  NATIVE_DEFINE_PROPERTY(window, "Amazify", {{
    value: publicRuntime,
    enumerable: false,
    configurable: true,
    writable: false
  }});

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
  window.dispatchEvent(new Event("amazify-runtime-cleanup-request"));
  document.querySelectorAll('[data-amazify-root="true"], [data-amazify-panel="true"], [data-amazify-menu="true"], [data-amazify-plugin-id], [data-amazify-style-id]').forEach((node) => node.remove());
  const runtimeStyle = document.getElementById("amazify-runtime-style");
  if (runtimeStyle) runtimeStyle.remove();
  return true;
})()
""".strip()
