# DevTools Methods Discovered From Amazon Music RPC

This file documents the working techniques discovered while building Amazon Music RPC. These methods are the technical foundation for an Amazify-style Amazon Music customization marketplace.

## 1. DevTools Launch

Amazon Music from the Microsoft Store can be launched with Chromium DevTools enabled by passing:

```text
--remote-debugging-port=<port>
```

Use a random free high port where possible. Avoid hardcoding `9222`.

The reliable launch flow is candidate-based:

1. Enumerate Start menu registrations with `Get-StartApps`.
2. Find entries named `Amazon Music`.
3. Enumerate packages with `Get-AppxPackage *AmazonMusic*`.
4. Build AUMID candidates from package family name plus manifest application ids.
5. Keep the known Store AUMID as a fallback:

```text
AmazonMobileLLC.AmazonMusic_kc6t79cpj4tp0!AmazonMobileLLC.AmazonMusic
```

6. Treat path-like AppIDs as executable candidates only if the file exists.
7. Launch AUMID candidates with `IApplicationActivationManager.ActivateApplication(appId, args)`.
8. Launch executable candidates directly with the same DevTools argument.
9. After every launch attempt, poll the selected port and only accept the candidate when a valid Amazon Music DevTools target appears.

Known failure mode:

- Website or alternate installs may reject `--remote-debugging-port=<port>` as an invalid option.
- Some registrations may look executable-like but are not valid launchers.
- If a candidate throws “Package was not found,” continue to the next candidate.

## 2. Target Validation

After launching, poll:

```text
http://127.0.0.1:<port>/json/list
```

Accept only targets that look like Amazon Music. Validate using a mix of:

- target title
- target URL
- app-specific page structure after `Runtime.evaluate`

Do not inject into arbitrary Chromium, Edge, Chrome, WebView2, or unrelated app targets.

## 3. CDP Runtime Evaluation

Use the target's `webSocketDebuggerUrl` and send Chromium DevTools Protocol messages.

Minimum method needed:

```json
{
  "id": 1,
  "method": "Runtime.evaluate",
  "params": {
    "expression": "(() => { return document.title; })()",
    "returnByValue": true,
    "awaitPromise": true
  }
}
```

Use `Runtime.evaluate` for:

- metadata probing
- header button injection
- CSS injection
- runtime loader installation
- MutationObserver setup
- local bridge calls from inside Amazon Music

## 4. Metadata Probe

Amazon Music exposes useful playback metadata in the DOM. The exact selectors can change, so use fallback probing.

Selectors that worked during Amazon Music RPC development:

```js
const title =
  document.querySelector('.trackMetadataWrapper .primaryContainer')?.textContent?.trim() ||
  document.querySelector('[data-testid*="track"]')?.textContent?.trim() ||
  "";

const secondary =
  document.querySelector('.trackMetadataWrapper .secondaryText')?.textContent?.trim() ||
  "";

const art =
  document.querySelector('.albumArt img.artImage')?.src ||
  document.querySelector('img[src*="images"]')?.src ||
  "";
```

Secondary text may appear as:

```text
Artist • Album
```

or sometimes as only:

```text
Artist
```

Do not drop metadata when the separator is missing. If a title exists and secondary has a single label, treat it as the artist unless a better album signal exists.

Also inspect:

```js
navigator.mediaSession?.metadata
```

It can expose title, artist, album, and artwork on some Chromium media pages.

## 5. Pause State and Time Bar

Useful sources:

- `document.querySelectorAll('audio, video')`
- `HTMLMediaElement.paused`
- `HTMLMediaElement.currentTime`
- `HTMLMediaElement.duration`
- Amazon Music progress bar DOM or ARIA labels

Preferred logic:

1. Use an audio/video element if visible to the page.
2. Fall back to Amazon progress DOM.
3. Fall back to metadata duration from an external lookup.
4. When playback resumes or a seek is detected, rescan the time bar.
5. If local time differs from displayed time by more than about one second, adjust the RPC or UI timer.

## 6. Header Button Injection

We proved Amazon Music can be modified at runtime by injecting DOM into the header.

Important lessons:

- Do not replace the Amazon Music logo.
- Find a stable container near the search bar or header navigation.
- Insert a new compact button next to existing controls.
- Use a unique root marker so the injection can be removed or updated.
- Use a MutationObserver because Amazon Music rerenders parts of the UI.

Recommended marker:

```html
<div data-amazify-root="true"></div>
```

Minimal injection shape:

```js
(() => {
  const existing = document.querySelector('[data-amazify-root="true"]');
  if (existing) existing.remove();

  const root = document.createElement('div');
  root.dataset.amazifyRoot = "true";
  root.style.display = "flex";
  root.style.alignItems = "center";
  root.style.gap = "8px";
  root.style.marginLeft = "8px";

  const button = document.createElement('button');
  button.textContent = "Amazify";
  button.style.border = "0";
  button.style.borderRadius = "999px";
  button.style.padding = "7px 12px";
  button.style.background = "#20d66b";
  button.style.color = "#07130b";
  button.style.fontWeight = "700";

  root.appendChild(button);

  const search = document.querySelector('input[type="search"], input[placeholder*="Search"]');
  const host = search?.closest('div')?.parentElement || document.querySelector('header') || document.body;
  host.appendChild(root);

  return true;
})();
```

For production, replace the selector logic with a ranked candidate search and layout checks.

## 7. Menu Injection

The Amazon Music RPC status menu proved that a polished in-app menu can work.

Known good pattern:

- Header button with logo plus status text.
- Solid menu panel, not transparent.
- Same visual tone as Amazon Music.
- Compact diagnostics rows.
- Toggle controls for privacy or plugin states.
- Close menu on outside click or route change.

Amazify can reuse this as:

- marketplace quick menu
- plugin enable/disable menu
- theme picker
- RPC status module

## 8. Localhost Bridge

We tested a local server and proved injected Amazon Music UI can call back to the companion app.

The working experiment:

1. Start a localhost server from the companion app.
2. Inject a button into Amazon Music.
3. Button calls a localhost endpoint.
4. Server returns a pong/state response.
5. Injected UI updates based on the response.

Possible bridge endpoints:

```text
GET  /state
POST /command
POST /plugins/enable
POST /plugins/disable
GET  /plugins
GET  /health
```

Bind only to:

```text
127.0.0.1
```

Use a random port and a per-session token if commands can change state.

Live prototype note:

- Amazon Music's HTTPS webapp may block injected page `fetch()` calls to localhost through CSP, mixed-content policy, or private-network access policy.
- Keep the localhost bridge, but provide a DevTools binding fallback for first-party Amazify UI commands.
- Do not give ordinary plugins unrestricted native binding access. Route plugin actions through the permissioned runtime API.

## 9. Plugin Runtime Loader

A marketplace should inject one stable loader, then let that loader mount plugins.

Runtime responsibilities:

- create one global `window.Amazify`
- mount plugin DOM
- inject plugin CSS
- remove plugin DOM/CSS by id
- hold bridge state
- expose a controlled command function
- avoid duplicate injection after reload

All plugin nodes should use:

```text
data-amazify-plugin-id="<plugin-id>"
```

All plugin styles should use:

```text
data-amazify-style-id="<plugin-id>"
```

## 10. Marketplace Safety Model

Themes and plugins can affect what Amazon Music displays, so treat them as code.

Minimum safety controls:

- disabled by default
- permission list before enabling
- per-plugin enable/disable
- one global emergency disable
- local plugin directory with clean deletion
- no silent remote plugin execution
- no arbitrary target injection
- no credential collection

Possible permission tiers:

```text
dom-style
dom-read
dom-write
bridge-state
bridge-command
network
```

Start with local-only plugin installation. Add remote marketplace later after a review/signing process exists.

## 11. What Might Be Possible Later

DevTools may expose enough DOM/state for:

- custom playlist/queue helpers
- next-song previews
- better Amazon-hosted cover art reuse
- compact now-playing overlays
- theme variables
- header command buttons
- playlist cleanup tools
- RPC status controls inside Amazon Music

Do not promise these until each page/state has been tested against the live app.

## 12. Known Brittleness

This approach is powerful but brittle because:

- Amazon Music can change DOM class names.
- Amazon can change the desktop app packaging.
- Some installers may reject Chromium flags.
- DevTools target titles and URLs can change.
- UI injection can be removed by React rerenders.
- Multiple Amazon Music windows can appear.
- A debugging port increases local attack surface if handled carelessly.

Mitigations:

- feature flags
- ranked selectors
- MutationObserver reinjection
- target validation
- random ports
- local-only bridge
- clear user opt-in
- fallback mode
- diagnostics view
