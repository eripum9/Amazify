# Coding AI Prompt

You are building `Amazify`, a Windows desktop customization marketplace for the Amazon Music desktop app. The product goal is similar in spirit to Spicetify, but for Amazon Music: users can install themes, small UI plugins, helper buttons, and settings panels that live directly inside Amazon Music.

The repository is intentionally new and separate from Amazon Music RPC. Do not copy Amazon Music RPC wholesale. Use the known DevTools and localhost bridge methods from `DEVTOOLS_METHODS.md` as the technical research base.

The product must feel Amazon Music native. The user should mostly forget that a separate companion app exists. The companion app should be a tiny non-visible background process whose job is only to keep the DevTools connection, local bridge, plugin storage, and Amazon Music launch/reconnect logic alive.

## Product Goal

Create a prototype marketplace app that can:

1. Launch or connect to Amazon Music with a Chromium DevTools debugging port.
2. Validate that the DevTools target is actually Amazon Music.
3. Inject a small runtime loader into Amazon Music.
4. Render an Amazify button in the Amazon Music header without replacing Amazon's logo or built-in controls.
5. Render the Amazify marketplace inside Amazon Music as Amazon-style UI.
6. Render Amazify settings inside Amazon Music as Amazon-style UI.
7. Let users install, enable, disable, and remove local plugins from inside Amazon Music.
8. Support a minimal plugin manifest format.
9. Support a theme plugin that injects CSS.
10. Support a UI plugin that injects a button/menu.
11. Keep all plugin state reversible without modifying Amazon Music files on disk.
12. Provide clear safety controls and a fallback mode when DevTools is unavailable.

## Non-Negotiable Requirements

- Do not patch, replace, or edit Amazon Music's installed files.
- Runtime changes must be injected only into the running Amazon Music renderer through DevTools.
- The marketplace UI must be inside Amazon Music, not in a separate visible desktop window.
- The settings UI must be inside Amazon Music, not in a separate visible desktop window.
- The companion app should be non-visible during normal use. A tray icon or debug window is acceptable only as an emergency/dev fallback, not the main UX.
- Enhanced injection must be opt-in and explain that it uses a local debugging interface.
- Use a random free high DevTools port per session where possible.
- Validate the DevTools target by URL/title before injecting anything.
- Do not connect to arbitrary browser targets.
- Do not expose a remote network server. Local bridge endpoints must bind only to localhost.
- Provide a one-click disable switch.
- Provide a clean uninstall path that removes Amazify settings, plugin files, and launcher shortcuts.
- Avoid storing secrets. If secrets are ever needed, use Windows DPAPI or Credential Manager.
- Keep plugins permissioned. A theme plugin should not automatically get bridge command access.

## Suggested Tech Stack

Use a pragmatic Windows-first stack:

- Python for the small background companion app and DevTools control, because Amazon Music RPC already proved this path works.
- No normal visible desktop shell. Avoid PySide6/WebView2 for the main marketplace or settings UI.
- Optional tiny tray icon only for emergency controls such as Quit, Repair Amazon Music launch, Disable Amazify, or Open Logs.
- A local plugin directory under `%APPDATA%\Amazify\plugins`.
- A local state directory under `%APPDATA%\Amazify`.
- JSON plugin manifests.
- Chromium DevTools Protocol over WebSocket for runtime evaluation.
- Injected HTML/CSS/JS for the marketplace and settings panels inside Amazon Music.
- A localhost-only bridge for plugin install/remove commands that require filesystem access.

If another stack is chosen, keep the same safety model and DevTools contract.

## Minimum Prototype

Build a first prototype with these parts:

1. `amazify_launcher`
   - Finds Amazon Music launch candidates.
   - Launches Amazon Music with `--remote-debugging-port=<port>`.
   - Supports UWP AUMID and executable candidates.
   - Supports a manual launcher override.

2. `devtools_client`
   - Polls `http://127.0.0.1:<port>/json/list`.
   - Finds the Amazon Music page target.
   - Connects to the WebSocket debugger URL.
   - Runs `Runtime.evaluate`.

3. `runtime_loader`
   - Injects a single Amazify root node into Amazon Music's header.
   - Uses a MutationObserver to reattach if Amazon rerenders the header.
   - Does not replace existing Amazon elements.
   - Adds a small button with the Amazify logo/text.
   - Owns all in-Amazon overlays, drawers, pages, modals, and settings panels.
   - Never requires the user to open a separate settings window.

4. `plugin_manager`
   - Reads plugin manifests from a local plugin folder.
   - Validates manifest shape.
   - Loads enabled CSS/JS plugin payloads.
   - Can disable a plugin and remove its injected nodes.

5. `marketplace_ui`
   - Is injected and rendered inside Amazon Music.
   - Opens from the Amazify header button.
   - Shows installed plugins using Amazon Music-style cards, rows, tabs, and modals.
   - Allows install from local `.zip` or folder first by calling the companion bridge.
   - Later can support a remote index.

6. `settings_ui`
   - Is injected and rendered inside Amazon Music.
   - Includes Amazify enable/disable, plugin permissions, launcher status, bridge status, theme options, and uninstall help.
   - Uses Amazon Music's visual language as much as possible.

7. `companion_app`
   - Runs in the background.
   - Starts minimized/non-visible.
   - Owns DevTools launch/reconnect.
   - Owns the local bridge.
   - Owns filesystem plugin install/update/remove.
   - Owns logs and diagnostics.
   - Must not become the main user interface.

## Plugin Manifest Draft

Use this as the first manifest idea:

```json
{
  "id": "example.theme.dark-green",
  "name": "Dark Green Theme",
  "version": "0.1.0",
  "author": "Amazify",
  "type": "theme",
  "description": "A compact green-accent Amazon Music theme.",
  "entry": "plugin.js",
  "styles": ["theme.css"],
  "permissions": ["dom-style"],
  "amazonMusic": {
    "testedAppVersions": [],
    "target": "desktop"
  }
}
```

Initial permission names:

- `dom-style`
- `dom-read`
- `dom-write`
- `bridge-state`
- `bridge-command`
- `network`

Default to the smallest permission set. Show permissions before enabling a plugin.

## Runtime Injection Contract

The injected runtime should create a global object:

```js
window.Amazify = {
  version: "0.1.0",
  plugins: new Map(),
  ui: {
    openMarketplace: () => {},
    openSettings: () => {},
    closePanel: () => {}
  },
  bridge: {
    getState: async () => {},
    command: async (name, payload) => {}
  },
  mountPlugin: async (manifest, source) => {},
  unmountPlugin: async (pluginId) => {}
};
```

Use stable DOM markers:

- `data-amazify-root`
- `data-amazify-panel`
- `data-amazify-marketplace`
- `data-amazify-settings`
- `data-amazify-plugin-id`
- `data-amazify-style-id`

All injected elements must be removable by plugin id.

## Known Amazon Music Methods

Read `DEVTOOLS_METHODS.md` before implementing. It contains the proven methods for:

- launching the Microsoft Store Amazon Music app with DevTools
- discovering AUMID and executable launch candidates
- validating the CDP target
- using `Runtime.evaluate`
- finding Amazon Music header/search areas
- injecting a header button without replacing the logo
- using a localhost bridge for ping/pong and RPC-style controls
- reading metadata, pause state, artwork, and timing
- avoiding brittle assumptions

## First Milestone Acceptance Criteria

- The app launches Amazon Music in DevTools mode or connects to an already launched DevTools session.
- An Amazify button appears next to the Amazon Music search/header area.
- Clicking the button opens an Amazify menu rendered inside Amazon Music.
- The menu can open the marketplace inside Amazon Music.
- The menu can open settings inside Amazon Music.
- There is no normal standalone visible marketplace/settings companion window.
- A sample theme plugin can be enabled and disabled.
- A sample button plugin can be enabled and disabled.
- Restarting Amazify removes all injected runtime elements before reinjecting.
- Closing Amazify leaves Amazon Music usable.
- Disabling DevTools mode leaves Amazon Music untouched.

## Safety and Trust Requirements

Include these in the UI:

- “Amazify customizes Amazon Music at runtime through a local DevTools connection.”
- “It does not modify Amazon Music files on disk.”
- “Plugins can change what the Amazon Music page displays.”
- “Only install plugins from sources you trust.”
- “The small background companion only handles Amazon Music connection, plugin files, and local commands.”

Add a security page before remote marketplace support:

- threat model
- plugin permissions
- local bridge scope
- uninstall steps
- how to report security issues

## Future Ideas

- plugin marketplace index
- screenshots/GIFs for plugins
- plugin update feed
- in-Amazon theme editor
- CSS variable inspector
- queue/playlist helpers if the Amazon DOM exposes enough data
- synced RPC status menu
- lyric overlay if a legal source exists
- per-plugin sandboxing or static review
- plugin signing
- compatibility reports for Amazon Music app versions

## Things to Avoid

- Do not build this as a browser extension. The target is the Windows desktop app.
- Do not build the marketplace as the main visible companion app UI.
- Do not build settings as the main visible companion app UI.
- Do not make the companion app feel like the product. Amazon Music is the product surface.
- Do not rely on one hardcoded DOM selector without fallbacks.
- Do not assume the website-installed Amazon Music is a raw executable.
- Do not assume `--remote-debugging-port=9222` is acceptable. Prefer random high ports.
- Do not put plugin code into Amazon Music's install folder.
- Do not silently enable DevTools or plugin injection.
- Do not claim affiliation with Amazon, Discord, or Spotify.
