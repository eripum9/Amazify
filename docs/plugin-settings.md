# Plugin Settings

Installed plugins have a Settings action in the marketplace. The resulting
plugin view contains its declared controls, any advanced UI registered while the
plugin is enabled, and the catalog update/reinstall action.

## Manifest Schema

Add a `settings` array to `manifest.json`. Amazify validates and bounds every
definition before catalog installation. Setting IDs must be unique and begin
with a lowercase ASCII letter.

Supported types:

| Type | Required fields | Stored value |
|---|---|---|
| `boolean` | `default` | Boolean |
| `color` | `default` as `#RRGGBB` | Lowercase hex color |
| `image` | Empty `default`; optional raster MIME `accept` list and `maxBytes` | Validated raster data URI or an empty string |
| `range` | Numeric `default`, `min`, `max`, and positive `step` | Bounded number |
| `select` | String `default` and unique `{value, label}` options | Selected string value |
| `text` | String `default`; optional `maxLength` and `placeholder` | Bounded string |

Every definition also requires `id`, `type`, and `label`; `description` is
optional. A plugin may declare at most 32 settings, and a select may contain at
most 64 options. Image controls accept PNG, JPEG, WebP, and GIF, default to a
1 MiB limit, and may not exceed 2 MiB. User-selected SVG is rejected because it
can contain active content; trusted SVG files can still be shipped as declared
plugin assets.

```json
{
  "settings": [
    {
      "id": "primaryColor",
      "type": "color",
      "label": "Main color",
      "description": "Primary highlights used by the theme.",
      "default": "#d9ff43"
    },
    {
      "id": "density",
      "type": "select",
      "label": "Density",
      "default": "compact",
      "options": [
        {"value": "compact", "label": "Compact"},
        {"value": "comfortable", "label": "Comfortable"}
      ]
    }
  ]
}
```

## Runtime API

The plugin receives an owner-scoped, frozen `Amazify.settings` object:

```javascript
const current = Amazify.settings.get("primaryColor");
const allValues = Amazify.settings.all();
const unsubscribe = Amazify.settings.subscribe((settings) => {
  document.body.style.setProperty("--plugin-primary", settings.primaryColor);
});

Amazify.settings.set("primaryColor", "#ff3366");
// Amazify.settings.reset() restores every declared default.

return () => unsubscribe();
```

`get` and `set` reject undeclared IDs and invalid values. `all` and subscription
snapshots are immutable copies. Subscriptions are revoked automatically during
plugin unmount, and settings survive disable, reinstall, and Amazify restarts.

For controls that cannot be represented declaratively, an enabled plugin may
call `Amazify.ui.addSettingsSection({id, title, render})`. Its render callback
receives an owned host in that plugin's settings view and may return a cleanup
function. The section and cleanup are removed automatically on disable.

Settings are stored in Amazon Music renderer local storage. They are preferences,
not a credential store: plugins share renderer authority and must never place
tokens, passwords, or other secrets in plugin settings.
