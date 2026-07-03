# Amazify

<img src="packaging/assets/logo.png" alt="Amazify logo" width="96">

Amazify is a Windows prototype for customizing the Amazon Music desktop app at runtime. It is inspired by and credits [Spicetify](https://spicetify.app/) for the core idea of user-controlled music app customization, but it targets Amazon Music through a local Python companion, Chromium DevTools injection, and a small in-app plugin marketplace.

The project does not patch Amazon Music files on disk. Amazify launches or connects to Amazon Music, injects a reversible runtime, and loads local open-source plugins from the user plugin folder.

## Credits

- [Spicetify](https://spicetify.app/) and its open-source ecosystem for proving how powerful a music-app customization marketplace can be.

## Current Status

This is an early prototype. The core flow works, but Amazon Music can change its launch behavior, DevTools target shape, or DOM selectors at any time.

Implemented:

- Python companion CLI
- Amazon Music launch candidate discovery
- Store/AUMID launch with Chromium DevTools enabled
- DevTools target validation and reconnect support
- Runtime injection and cleanup
- In-Amazon Amazify header button
- In-Amazon marketplace and settings panel
- Local installed plugin manifests under `%APPDATA%\Amazify\plugins`
- GitHub-backed plugin catalog with explicit Download/Update actions
- Permissioned plugin metadata
- One-click disable for all plugins
- Localhost bridge with DevTools binding fallback
- Stock sample plugins

## Requirements

- Windows
- Python 3.10+
- Amazon Music desktop app

The standalone Windows installer is experimental and not published as a ready user build yet. When it is ready, `AmazifySetup.exe` will copy a standalone `amazify.exe` into `%LOCALAPPDATA%\Programs\Amazify`, add that folder to the user PATH, and register a user-level uninstall entry.

```powershell
AmazifySetup.exe
```

For now, use this only for local packaging tests.

For source development with Python:

```powershell
python -m pip install -e .
```

Build the standalone CLI and installer locally:

```powershell
python -m pip install -e ".[build]"
.\Build.bat
```

The build writes `dist\amazify.exe` and `dist\AmazifySetup.exe`.

## Run

Show available commands:

```powershell
amazify
```

Launch or connect to Amazon Music and inject Amazify:

```powershell
amazify run
```

Connect to an already running Amazon Music DevTools session:

```powershell
amazify run --connect-only --devtools-port <port>
```

List detected Amazon Music launch candidates:

```powershell
amazify list-candidates
```

Run tests:

```powershell
python -m unittest discover -s tests -v
```

## Plugin Catalog

Catalog metadata lives in `plugin_catalog.json`. By default Amazify reads it from:

```text
https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json
```

The catalog points each plugin file at a raw GitHub URL. The marketplace shows catalog entries with a **Download** button. Downloading copies the raw plugin files into `%APPDATA%\Amazify\plugins`.

Every time the marketplace opens, Amazify refreshes the catalog and compares each catalog manifest version with the installed plugin manifest version. Installed catalog-backed plugins show **Update** when the GitHub catalog has a newer version, or **Reinstall** when the installed version already matches the catalog.

For local development, override the catalog URL:

```powershell
$env:AMAZIFY_PLUGIN_CATALOG_URL = "file:///C:/path/to/plugin_catalog.json"
python -m amazify
```

## Stock Plugins

Stock plugin source lives in `sample_plugins/`. These folders are source code for the GitHub catalog, not automatically installed plugin copies.

- `amazify.true-big-mode`: replaces Amazon Music Big Mode with a full-window lyrics-focused layout, album-art exit behavior, hidden queue/device controls, and a custom progress/control overlay.
- `amazify.resume-last-song`: saves the current transport track locally and tries to resume it on the next Amazon Music launch.
- `amazify.theme.dark-green`: green Amazon Music theme.
- `amazify.button.focus-mode`: small header action that toggles a quieter focus mode.

Downloaded plugins are disabled by default. Enable them from the Amazify marketplace inside Amazon Music.

## Plugin Shape

Each plugin is a folder with a `manifest.json` and optional JavaScript/CSS sources:

```json
{
  "id": "amazify.example",
  "name": "Example Plugin",
  "version": "0.1.0",
  "author": "Amazify",
  "type": "ui",
  "description": "Short user-facing description.",
  "entry": "plugin.js",
  "styles": ["style.css"],
  "assets": {
    "logo": "assets/logo.svg",
    "displayFont": "assets/display.woff2"
  },
  "permissions": ["dom-read", "dom-write"],
  "amazonMusic": {
    "testedAppVersions": [],
    "target": "desktop"
  }
}
```

Plugin JavaScript is executed with `Amazify`, `manifest`, and `source` arguments. If it returns a function, Amazify calls that function during plugin cleanup.

Assets can be any plugin-local file such as PNG, SVG, WEBP, WOFF2, or JSON. Declare them in `assets` as a list of paths or a name-to-path map. Runtime CSS automatically rewrites matching local `url(...)` references to safe data URIs. JavaScript can use `Amazify.assets.url(manifest.id, "logo")`, `Amazify.assets.get(manifest.id, "logo")`, or `source.assetUrl("logo")`.

All plugin DOM should be removable and scoped with `data-amazify-plugin-id` when creating persistent nodes. Plugin CSS is mounted and removed automatically by plugin id.

## Safety Model

Amazify treats plugins as code:

- Stock marketplace plugins should be tested and open source.
- Third-party plugins should be marked as untrusted until reviewed.
- Permissions should stay narrow.
- Runtime changes must be reversible.
- Amazon Music packaged files should not be modified.

## Repository Layout

```text
amazify/          Python companion, launcher, bridge, runtime injection
amazify/assets/   Small packaged Amazify logo used by the in-app overlay
Build.bat
                  Builds the standalone CLI and Windows installer on Windows
.github/workflows/
                  Windows installer artifact build
packaging/        PyInstaller entrypoints for the CLI and installer
packaging/assets/ Amazify logo PNG and Windows ICO used for the executables
plugin_catalog.json
                  GitHub-backed marketplace catalog
sample_plugins/  Stock plugin source for the catalog
tests/           Unit tests for launcher, runtime, and plugin manager
```

## Development Notes

Amazify stores runtime state outside the repo:

- Plugins: `%APPDATA%\Amazify\plugins`
- State: `%APPDATA%\Amazify`
- Logs: `%APPDATA%\Amazify\logs`

If a stock plugin changes, push the update to GitHub. Users can press **Update** in the marketplace to pull the current raw plugin files.
