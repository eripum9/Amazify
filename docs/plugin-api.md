# Plugin API

The injected runtime passes each enabled plugin an owner-scoped `Amazify`
object. Runtime APIs are revoked when that plugin is unmounted. Plugins still
run in the Amazon Music renderer, so the API is not a JavaScript sandbox.

## Fullscreen

`Amazify.fullscreen` is a frozen API available to enabled plugins. It uses the
browser Fullscreen API and preserves the native user-gesture requirement.
The companion mirrors entry/exit to a reversible borderless Windows frame,
because Amazon's embedded browser does not resize its desktop window itself.
The original position, maximized state and frame are restored on exit or
companion disconnection. Ambiguous/multiple Amazon windows are not modified.
Desktop frame errors appear in the core settings; a `request()` result confirms
the browser transition, not the asynchronous Windows frame operation.

```javascript
const stop = Amazify.fullscreen.subscribe((state) => {
  console.log(state.active, state.element);
});

async function enterFullscreen() {
  const entered = await Amazify.fullscreen.request();
  if (entered === true) {
    // The plugin owns this fullscreen session and may release it later.
  }
}

return () => stop();
```

| Member | Semantics |
|---|---|
| `available` | Dynamic boolean indicating whether the browser exposes an enabled request method. |
| `active` | Dynamic boolean indicating whether a native fullscreen element exists. |
| `request(element?)` | Returns `Promise<boolean>`. `true` means entry was confirmed by the native state or `fullscreenchange`; `false` means unavailable, already active, rejected, superseded, or not confirmed before the bounded timeout. A request must be made during a user gesture when the browser reports that requirement. Successful requests are owned by the calling plugin. |
| `exit()` | Requests the current native fullscreen session to exit. This is an explicit global exit operation; it is not restricted to the calling plugin. |
| `release()` | Releases the calling plugin's ownership. It exits fullscreen only when the plugin still owns the exact current fullscreen session. It does not exit a session entered later by the user or another plugin. |
| `getState()` | Returns a shallow-frozen snapshot: `{available, active, element}`. The native `element` reference is not frozen. After unmount, the plugin receives an inactive snapshot with `element: null`. |
| `isActive()` | Returns whether the plugin is mounted and a native fullscreen element exists. |
| `subscribe(listener)` | Immediately calls `listener` with a snapshot and calls it again for native fullscreen changes or request errors. Returns an unsubscribe function; unsubscribing affects only that subscription. |

Requests that return `false` do not indicate that the browser entered
fullscreen. A plugin should treat `true` as the only successful result and
should unsubscribe listeners from its cleanup function.

## Runtime F11 Preference

The core runtime exposes an **F11 fullscreen shortcut** preference in its
Preferences view. It is enabled by default and can be disabled by the user.
When enabled, an unmodified F11 key press toggles browser fullscreen; key
repeat events and modified F11 combinations are ignored. The runtime prevents
the handled F11 event from also triggering a second browser action.

True Big Mode's **Enter fullscreen automatically** option is a user-facing setting. It lets
that presentation request fullscreen at its supported user interaction points;
it is separate from the core F11 preference and is not a plugin API contract.
