# Amazify

<img src="packaging/assets/logo.png" alt="Amazify logo" width="96">

**Amazon Music runtime customization marketplace — inspired by [Spicetify](https://spicetify.app/).**

Amazify is a Windows companion that customizes the Amazon Music desktop app at runtime without modifying any packaged files on disk. It launches or connects to Amazon Music, injects a reversible runtime via Chromium DevTools, and loads plugins from an in-app marketplace.

[![Windows CI](https://github.com/eripum9/Amazify/actions/workflows/ci-windows.yml/badge.svg)](https://github.com/eripum9/Amazify/actions/workflows/ci-windows.yml)
[![Security](https://github.com/eripum9/Amazify/actions/workflows/security.yml/badge.svg)](https://github.com/eripum9/Amazify/actions/workflows/security.yml)

---

## Features

- **Runtime injection** — injects a reversible runtime into Amazon Music without touching app files
- **In-app marketplace** — browse, download, and update plugins from inside Amazon Music
- **Plugin catalog** — GitHub-backed catalog with explicit Download/Update/Reinstall actions
- **Persistent launch supervisor** — starts at sign-in, accepts launch requests, and stays idle when Amazon Music closes
- **Fast DevTools reconnect** — discovers ports from running Amazon Music processes and probes candidates concurrently
- **Localhost bridge** — authenticated loopback HTTP bridge with a DevTools binding fallback
- **Stock plugins** — a curated set of tested layout and interface plugins
- **Permissioned metadata** — each plugin declares permissions and receives only declared Amazify capabilities
- **GUI installer** — Inno Setup 6 installer with optional desktop and taskbar shortcuts
- **Application updater** — checks final GitHub releases and verifies the installer SHA-256 before launch

---

## Requirements

| Requirement | Version |
|---|---|
| Windows | 10 or later |
| Python | 3.10+ |
| Reproducible CI/build Python | 3.12.10 |
| Amazon Music | Desktop app |

---

## Installation

### From source (recommended for development)

```powershell
git clone https://github.com/eripum9/Amazify.git
cd Amazify
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

### Standalone installer

Until the 1.0.0 release is published, build the installer locally with the steps in the [Development](#development) section and run:

```powershell
.\dist\AmazifySetup.exe
```

The installer copies `amazify.exe` and the windowless launcher (`amazifyw\`) into `%LOCALAPPDATA%\Programs\Amazify`, adds that folder to the user `PATH`, registers a user-level uninstall entry, and creates a **Start Menu** shortcut named **Amazon Music (Amazify)**. Its Additional Tasks page can enable startup-at-sign-in, a Desktop shortcut, and taskbar pinning. Startup-at-sign-in is selected by default.

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

`amazify run` starts the daemon if needed, sends it an Amazon Music open/focus request, and returns immediately. The daemon keeps running after the terminal and Amazon Music close. For foreground/debug mode:

```powershell
amazify run --foreground
```

Manage the daemon:

```powershell
amazify daemon start
amazify daemon status
amazify daemon stop
```

Check or install a final Amazify application release:

```powershell
amazify --version
amazify update check
amazify update install
```

Application updates are never installed silently. Amazify requires an explicit
confirmation, downloads only the official `AmazifySetup.exe` release asset,
checks its GitHub-provided SHA-256 digest, and then opens the normal installer.
See [application updates](docs/application-updates.md) for the accepted release
contract and maintainer checklist.

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
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

### Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests --cov=amazify --cov-report=term-missing --cov-fail-under=45
.\.venv\Scripts\python.exe -m ruff check amazify packaging tests --select E9,F63,F7,F82
.\.venv\Scripts\python.exe -m pyright amazify/bridge.py amazify/config.py amazify/devtools.py amazify/native_bridge.py amazify/shortcuts.py amazify/window_identity.py packaging/amazify_installer.py .github/scripts/validate_candidate.py tests/test_workflow_security.py
```

### Build standalone executables and installer

Local packaging requires [Inno Setup 6](https://jrsoftware.org/isdl.php)
(`ISCC.exe`) on `PATH` or in its default install directory. The official
candidate workflow verifies Inno Setup 6.7.3 and CPython 3.12.10.

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
.\Build.bat
```

Outputs:

| File | Description |
|---|---|
| `dist\amazify.exe` | Console CLI |
| `dist\amazifyw\amazifyw.exe` | Windowless launcher |
| `dist\AmazifySetup.exe` | GUI installer |

The manual **Build Windows Candidate** workflow performs the same build with
tests, dependency audits, executable and isolated installer smoke tests,
checksums, runtime/build SBOMs, security evidence, and GitHub provenance attestations. It
uploads an Actions artifact only. It cannot create a draft or publish a GitHub
release. See [Windows candidate builds](docs/candidate-builds.md) and
[dependency management](docs/dependency-management.md).

---

## Plugin Catalog

The update index is defined in the schema-v2 `plugin_catalog.json` and hosted at:

```
https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json
```

Each catalog package declares a trust tier, source repository, immutable
40-character Git commit, and the SHA-256 and byte size of every file. Amazify
derives and validates raw GitHub download URLs from those fields rather than
trusting mutable per-file branch URLs. When the marketplace opens, Amazify
refreshes the index and compares verified manifest versions against installed
versions. Installed plugins show **Update** when a newer revision is available,
or **Reinstall** when already up to date.

Unfrozen source builds can explicitly opt into a local catalog during
development:

```powershell
$env:AMAZIFY_PLUGIN_CATALOG_URL = "file:///C:/path/to/plugin_catalog.json"
$env:AMAZIFY_ALLOW_LOCAL_CATALOG = "1"
.\.venv\Scripts\python.exe -m amazify
```

Frozen production builds do not enable a local catalog from an environment
variable alone.

---

## Stock Plugins

Source lives in `sample_plugins/`. These are catalog source folders — they are not installed automatically.

| Plugin ID | Description |
|---|---|
| `amazify.true-big-mode` | Full-window lyrics layout with custom overlay, replaces Amazon Music Big Mode |
| `amazify.theme.signal-studio` | Full interface redesign with a navigation rail, reactive ambience, custom typography, and floating transport |

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
  "permissions": ["dom-read", "dom-write", "dom-style"],
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
- Treat community plugins as untrusted even after integrity verification.
- `dom-read`, `dom-write`, `dom-style`, and `network` disclose renderer-level
  authority; they do not form a complete JavaScript sandbox.
- Read the [security policy](SECURITY.md), [threat model](docs/threat-model.md),
  and [network endpoint inventory](docs/network-endpoints.md) before adding a
  privileged capability.

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
.github/workflows/    Pinned CI, security, and non-publishing candidate workflows
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
2. Install `requirements-dev.lock` with `--require-hashes` and run the checks in
   [Development](#development).
3. Keep changes focused and include tests for new behavior where practical.
4. Open a pull request with a clear description of the change.

---

## Credits

- [Spicetify](https://spicetify.app/) and its community for pioneering music app customization marketplaces.

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
