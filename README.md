# Amazify

<img src="packaging/assets/logo.png" alt="Amazify logo" width="96">

**Amazon Music runtime customization marketplace — inspired by [Spicetify](https://spicetify.app/).**

Amazify is a Windows prototype that customizes the Amazon Music desktop app at runtime without modifying any packaged files on disk. A local Python companion launches or connects to Amazon Music, injects a reversible runtime via Chromium DevTools, and loads plugins from an in-app marketplace.

[![Windows CI](https://github.com/eripum9/Amazify/actions/workflows/ci-windows.yml/badge.svg)](https://github.com/eripum9/Amazify/actions/workflows/ci-windows.yml)

---

## Features

- **Runtime injection** — injects a reversible runtime into Amazon Music without touching app files
- **In-app marketplace** — browse, download, and update plugins from inside Amazon Music
- **Plugin catalog** — GitHub-backed catalog with explicit Download/Update/Reinstall actions
- **Background daemon** — headless daemon with `start` / `stop` / `status` CLI commands
- **DevTools reconnect** — automatic reconnect when Amazon Music restarts
- **Localhost bridge** — WebSocket bridge with DevTools binding fallback
- **Stock plugins** — four ready-to-use sample plugins (themes, layout, resume, focus mode)
- **Permissioned metadata** — each plugin declares required permissions in its manifest
- **GUI installer** — Inno Setup 6 installer with optional desktop and taskbar shortcuts

---

## Requirements

| Requirement | Version |
|---|---|
| Windows | 10 or later |
| Python | 3.10+ |
| Amazon Music | Desktop app |

---

## Installation

### From source (recommended for development)

```powershell
git clone https://github.com/eripum9/Amazify.git
cd Amazify
python -m pip install -e .
```

### Standalone installer (experimental)

The GUI installer is not yet published as a public release. Build it locally with the steps in the [Development](#development) section and run:

```powershell
.\dist\AmazifySetup.exe
```

The installer copies `amazify.exe` and the windowless launcher (`amazifyw\`) into `%LOCALAPPDATA%\Programs\Amazify`, adds that folder to the user `PATH`, registers a user-level uninstall entry, and creates a **Start Menu** shortcut named **Amazon Music (Amazify)**.

> **Note:** Taskbar pinning is best-effort. If Windows refuses the programmatic pin, pin **Amazon Music (Amazify)** manually from Start.

---

## Usage

Show available commands:

```powershell
amazify
```

Launch or connect to Amazon Music and inject Amazify:

```powershell
amazify run
```

`amazify run` starts the background daemon and returns immediately. The daemon keeps running after the terminal closes. For foreground/debug mode:

```powershell
amazify run --foreground
```

Manage the daemon:

```powershell
amazify daemon start
amazify daemon status
amazify daemon stop
```

Connect to an already-running Amazon Music DevTools session:

```powershell
amazify run --connect-only --devtools-port <port>
```

List detected Amazon Music launch candidates:

```powershell
amazify list-candidates
```

---

## Development

### Setup

```powershell
python -m pip install -e .
```

### Run tests

```powershell
python -m unittest discover -s tests -v
```

### Build standalone executables and installer

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php) (`ISCC.exe`) on `PATH` or in its default install directory.

```powershell
python -m pip install -e ".[build]"
.\Build.bat
```

Outputs:

| File | Description |
|---|---|
| `dist\amazify.exe` | Console CLI |
| `dist\amazifyw\amazifyw.exe` | Windowless launcher |
| `dist\AmazifySetup.exe` | GUI installer |

---

## Plugin Catalog

The catalog is defined in `plugin_catalog.json` and hosted at:

```
https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json
```

Each entry points plugin files at raw GitHub URLs. When the marketplace opens, Amazify refreshes the catalog and compares catalog manifest versions against installed versions. Installed plugins show **Update** when a newer version is available, or **Reinstall** when already up to date.

To use a local catalog during development:

```powershell
$env:AMAZIFY_PLUGIN_CATALOG_URL = "file:///C:/path/to/plugin_catalog.json"
python -m amazify
```

---

## Stock Plugins

Source lives in `sample_plugins/`. These are catalog source folders — they are not installed automatically.

| Plugin ID | Description |
|---|---|
| `amazify.true-big-mode` | Full-window lyrics layout with custom overlay, replaces Amazon Music Big Mode |
| `amazify.resume-last-song` | Saves and restores the current track across Amazon Music restarts |
| `amazify.theme.dark-green` | Green color theme for Amazon Music |
| `amazify.button.focus-mode` | Header button that toggles a quieter focus mode |

Downloaded plugins are **disabled by default**. Enable them from the Amazify marketplace inside Amazon Music.

---

## Plugin Development

Each plugin is a folder containing a `manifest.json` and optional JavaScript/CSS files:

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
    "logo": "assets/logo.svg"
  },
  "permissions": ["dom-read", "dom-write"],
  "amazonMusic": {
    "testedAppVersions": [],
    "target": "desktop"
  }
}
```

- Plugin JavaScript receives `Amazify`, `manifest`, and `source` arguments. Returning a function registers it as a cleanup callback.
- Assets (PNG, SVG, WEBP, WOFF2, JSON) are declared in `assets`. Runtime CSS automatically rewrites matching `url(...)` references to safe data URIs.
- Use `Amazify.assets.url(manifest.id, "logo")` or `source.assetUrl("logo")` in JavaScript.
- All plugin DOM must be removable and scoped with `data-amazify-plugin-id`.

### Safety guidelines

- Declare only the permissions your plugin actually needs.
- All runtime DOM changes must be fully reversible.
- Do not modify Amazon Music packaged files on disk.
- Third-party plugins should be treated as untrusted until reviewed.

---

## Repository Layout

```
amazify/              Python companion — launcher, DevTools bridge, runtime, plugin manager, CLI
amazify/assets/       Packaged Amazify logo (in-app overlay)
tests/                Unit tests
sample_plugins/       Stock plugin source (catalog source, not auto-installed)
packaging/            PyInstaller entry points and Inno Setup installer script
packaging/assets/     Logo PNG and ICO for executables and installer
plugin_catalog.json   GitHub-backed marketplace catalog
Build.bat             Builds standalone executables and GUI installer
.github/workflows/    CI workflows
```

---

## Runtime State

Amazify stores all runtime state outside the repository:

| Path | Contents |
|---|---|
| `%APPDATA%\Amazify\plugins` | Installed plugins |
| `%APPDATA%\Amazify` | Config and state files |
| `%APPDATA%\Amazify\logs` | Log files |

---

## Contributing

Contributions are welcome. Please:

1. Fork the repository and create a feature branch.
2. Run `python -m unittest discover -s tests -v` and ensure all tests pass.
3. Keep changes focused and include tests for new behavior where practical.
4. Open a pull request with a clear description of the change.

---

## Credits

- [Spicetify](https://spicetify.app/) and its community for pioneering music app customization marketplaces.

---

## License

No license has been specified for this project yet. All rights reserved until a license is added.
