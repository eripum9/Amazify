# Amazify Threat Model

## Scope And Security Goal

This model covers the Windows companion, daemon, installer, DevTools transport,
loopback HTTP bridge, native DevTools binding, injected runtime, plugin manager,
catalog, local state, and candidate-build pipeline.

The goal is to let a user intentionally customize Amazon Music while preventing
untrusted websites, unrelated local debugging services, tampered downloads, and
plugins without the required capability from gaining Amazify authority.

## Protected Assets

- The user's authenticated Amazon Music renderer and data visible in its DOM.
- Playback integrity and actions performed through Amazon Music controls.
- Ephemeral bridge tokens, native-binding nonces, and DevTools session details.
- Optional Spotify access/refresh tokens and OAuth PKCE state used by Karaoke Lyrics.
- Installed plugin source, enabled state, catalog cache, settings, and logs.
- The integrity and provenance of official catalog entries and candidate artifacts.
- The integrity and provenance of application update metadata and installers.
- The user's filesystem, startup configuration, shortcuts, and installed Amazify files.

Amazon credentials, DRM keys, and subscription bypass are neither required nor
intended Amazify assets. Code that attempts to collect or bypass them is outside
the supported plugin model.

## Actors And Inputs

- **User:** chooses plugins, starts Amazon Music, and approves install/enable actions.
- **Amazify maintainer:** controls the official repository, catalog, and workflow definitions.
- **Stock plugin author:** supplies reviewed source pinned by the official catalog.
- **Community plugin author:** supplies third-party code that must be treated as untrusted.
- **Remote attacker:** may control a website, catalog response, plugin repository,
  redirect destination, compromised dependency, or submitted workflow input.
- **Local attacker:** may run a different loopback service or process as the same user.
- **Upstream applications:** Amazon Music, Chromium DevTools, Windows, GitHub,
  PyPI, and Inno Setup can change behavior outside Amazify's control.

Attacker-controlled input includes target metadata, URLs, WebSocket endpoints,
HTTP headers and bodies, plugin manifests and files, catalog metadata, redirects,
local JSON state, process command lines, workflow inputs, and archive contents.

## Trust Boundaries

### Amazon Music DevTools Boundary

Amazify opens or discovers a loopback DevTools listener. Before evaluating code,
it must validate an exact supported Amazon Music HTTPS origin, page target type,
target identifier, loopback WebSocket host, selected port, `/devtools/page/<id>`
path, and listener ownership by the expected Amazon Music process tree. Target
metadata and page titles alone are not trust signals.

The WebSocket connection explicitly bypasses ambient proxy settings, binds the
expected listener to a stable process identity rather than a reusable PID, and
revalidates ownership immediately after connecting. Packaged executable paths
must resolve beneath a protected `Program Files\\WindowsApps` root with the
canonical Amazon Music package directory grammar.

### Loopback HTTP Bridge Boundary

The bridge is reachable by local processes and potentially by browser pages.
Only `/health` is unauthenticated and it returns no state. Other requests require
an unpredictable per-session token, an approved Amazon Music origin where an
Origin header is present, a valid loopback Host header, a permitted method/path,
strict JSON, and a maximum 16 KiB request body. Responses are non-cacheable.

### Native Binding Boundary

The DevTools binding bypasses browser CORS and therefore requires its own random
session nonce and command allowlist. Runtime code captures the binding before
plugins mount, removes mutable global access, and rejects stale or malformed
messages. A plugin receives only the frozen capabilities declared for it.

### Plugin Execution Boundary

Plugin files are untrusted until catalog and package verification succeeds.
Verified JavaScript still executes in Amazon Music's renderer. DOM and network
permissions disclose risk but do not create a complete JavaScript sandbox.
Bridge capabilities, lifecycle mutation, and Amazify secrets must not be ambient
globals. Privileged lifecycle controls require trusted user activation.
Community plugins install disabled and require explicit enablement. Any changed
package identity, including a new commit, file inventory, manifest, or permission
set, is installed disabled and must be enabled again.

The runtime capability registry is owner-scoped and lifecycle-scoped. Capability
names must be provider-namespaced, consumers pin the expected provider and major
version, and provider APIs are frozen and revoked on unmount. This limits
accidental substitution and stale access; it does not sandbox mutually malicious
code because all enabled plugins still share the Amazon renderer.

### Lyrics Provider Boundary

Only `amazify.karaoke-lyrics` may declare `lyrics-provider`. Spotify OAuth and
provider traffic execute in the native companion, not plugin JavaScript. OAuth
uses Authorization Code with PKCE, a random loopback callback port and state,
no client secret, and no scopes. Access tokens remain in memory and refresh
tokens use Windows DPAPI. The broker accepts only exact Spotify auth/token/search
and Spicy Lyrics query paths, rejects redirects, bounds bodies and timeouts, and
discards canceled or stale requests before replying to the renderer.

Spicy Lyrics receives the no-scope Spotify bearer token as required by its web
authentication protocol. It is an external service and therefore a distinct
trust boundary. Users who do not connect Spotify, are not allowlisted by a
development-mode Spotify app, or encounter a provider failure retain Amazon's
line-synchronized lyrics fallback.

### Catalog And Download Boundary

The catalog is an update index, not executable authority by itself. Each package
identifies its source repository and full 40-character Git commit. Every file has
a normalized relative path, advertised size, and SHA-256. HTTPS, host, repository,
commit, redirect count, path containment, response size, and final hash are
validated before parsing or installation. Installation uses a unique staging
directory and atomic replacement with rollback. Plugin identifiers are also
validated as canonical Windows-safe directory names before any filesystem path
is derived, including checks for trailing aliases and reserved device names.

### Local State And Installer Boundary

State under `%APPDATA%\Amazify` is user-writable and must be parsed defensively.
Updates use atomic writes and preserve a valid prior state on failure. The
installer operates per-user, stops the daemon before replacing files, and smoke
tests use a dedicated mode that avoids startup, PATH, shortcut, and daemon side
effects.

### Application Update Boundary

The updater trusts only the exact public GitHub release API endpoint for this
repository and only final `vmajor.minor.patch` releases. It accepts exactly one
`AmazifySetup.exe` asset whose URL, size, and GitHub-provided SHA-256 digest are
present and valid. Metadata is bounded and redirects are rejected. Installer
downloads permit at most three HTTPS redirects to a small GitHub release-asset
host allowlist, enforce the advertised size while streaming, stage atomically,
and are verified again immediately before process launch. Download and install
are separate from plugin updates. Installation requires explicit trusted user
activation or command-line confirmation and is never silent.

### GitHub Actions Boundary

Repository content, dependency metadata, and manual inputs are untrusted build
inputs. Workflows pin actions by commit, disable persisted checkout credentials,
use hash-locked Python dependencies, pass user input through environment
variables, and grant only job-specific permissions. Candidate artifacts are
attested and uploaded to the workflow run; no release is created.

## Threats And Required Mitigations

| Threat | Required mitigation |
| --- | --- |
| Attach to an unrelated or attacker-controlled DevTools listener | Random loopback port, exact target/WS validation, protected package path, process creation-time identity, pre/post-connect listener validation, bounded target list |
| Ambient proxy redirects loopback DevTools traffic | Explicit loopback no-proxy routing and post-connect listener validation |
| Website invokes bridge commands | Exact origin and Host checks, random token, constant-time comparison, allowlisted routes, 16 KiB body limit |
| Plugin captures bridge credentials or native authority | Capture native primitives before old cleanup and plugin load, remove mutable globals, frozen per-plugin capabilities, captured request serialization, nonce validation |
| Catalog points to mutable or substituted code | Full commit pin, per-file size and SHA-256, strict URL/redirect validation |
| Plugin path escapes its install root | Normalize relative paths, reject absolute/traversal paths and links/reparse points |
| Windows aliases one plugin ID to another directory | Canonical ID grammar, no trailing/double-dot components, reserved-device rejection |
| Changed plugin code inherits prior execution consent | Preserve enabled state only for an identical verified package identity; install every changed package disabled |
| Plugin synthesizes privileged marketplace interactions | Require trusted user activation at every lifecycle handler |
| Failed update destroys a working plugin | Unique staging path, verify before activation, locked atomic swap with backup and rollback |
| Application update substitutes an installer | Exact final-release metadata, exact asset name and URL, bounded redirects, size enforcement, mandatory GitHub SHA-256 digest, atomic staging, pre-launch re-verification |
| Plugin or website starts an application update | Native-binding-only app-update commands, hidden nonce, no plugin command exposure, trusted UI click, CLI confirmation |
| Concurrent bridge requests corrupt plugin state | Synchronize catalog, install, and state operations; use atomic state files |
| Workflow dependency or action substitution | Hash-locked Python environment, full action SHAs, Dependabot, pip-audit, CodeQL, dependency review |
| Workflow input executes shell code | Put expression values in step `env`; validate format before use; never interpolate inputs into `run` blocks |
| Candidate is mistaken for an official release | Candidate naming and documentation, no release API commands, no `contents: write` |
| Sensitive data appears in diagnostics or artifacts | Do not log session credentials; redact paths/tokens; keep evidence to versions, hashes, and check results |
| A lyrics plugin steals native Spotify authority | Reserve `lyrics-provider` for the exact stock plugin ID, expose frozen narrow methods, keep tokens native-only, revoke on unmount |
| Stale provider work replaces the current song | Track generations and request keys, cancel prior work, reject late track keys, stop executor replies after bridge close |
| Provider redirects or returns oversized/malformed content | Exact HTTPS host/path allowlist, no redirects/proxies, strict content type and JSON, short timeouts and byte limits |

## Residual Risks

- Enabled plugin JavaScript shares the Amazon Music renderer and can exercise the
  page-level authority covered by its disclosures.
- A same-user process may inspect files or memory and can often automate the UI.
- DevTools intentionally expands the local attack surface while Amazon Music is attached.
- Catalog review, hashes, and provenance establish identity and integrity, not correctness.
- Unsigned executables do not provide Authenticode publisher identity and may trigger SmartScreen.
- The updater's release identity ultimately depends on the security of the official GitHub repository and maintainer account.
- Amazon Music DOM and launch behavior are unsupported upstream interfaces and may break safely or unexpectedly.
- The shared Karaoke Lyrics renderer and capability consumers remain a renderer-level trust boundary.
- Spicy Lyrics is an undocumented third-party service and may change, rate-limit, or reject compatibility requests.

Sensitive findings should be reported as described in [`SECURITY.md`](../SECURITY.md).
