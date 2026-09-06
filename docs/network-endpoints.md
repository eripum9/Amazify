# Network Endpoints And Limits

Amazify does not provide telemetry and does not intentionally upload logs,
settings, cookies, or Amazon credentials. Amazon Music and enabled plugins have
their own network behavior, which is separate from the companion's requests.

## Runtime Remote Endpoints

Karaoke Lyrics 0.2.0 uses public Better Lyrics and Unison endpoints. The archived
Spotify authentication module is dormant; no active runtime path invokes it.

| Destination | Purpose | Authentication and validation | Limit |
| --- | --- | --- | --- |
| `https://api.github.com/repos/eripum9/Amazify/releases/latest` | Check the latest final Amazify application release | HTTPS, exact API URL, no redirects, bounded strict JSON, exact repository/tag/release/asset validation | 256 KiB response |
| `https://github.com/eripum9/Amazify/releases/download/v<version>/AmazifySetup.exe` | Download a user-approved application update | HTTPS, exact repository/tag/asset path, at most three validated redirects to GitHub release-asset hosts, advertised size, mandatory GitHub SHA-256 digest | 256 MiB installer |
| `https://raw.githubusercontent.com/eripum9/Amazify/main/plugin_catalog.json` | Fetch the official catalog update index when the store opens | HTTPS, exact host/repository/path, bounded response, schema validation | 1 MiB response |
| `https://raw.githubusercontent.com/<owner>/<repo>/<40-char-commit>/<path>` | Fetch a catalog-pinned manifest, script, stylesheet, font, image, or other declared asset | HTTPS, catalog-approved repository and commit, normalized path, advertised byte size, SHA-256 | 2 MiB code/config file; 5 MiB declared asset |
| `https://lyrics-api.boidu.dev/getLyrics` | Optional rich lyrics; sends title, artist, album and duration | Public GET without credentials; exact HTTPS host/path, no redirects/proxies, strict JSON and bounded TTML | 1 MiB response; 8-second socket timeout |
| `https://unison.boidu.dev/lyrics` | Second rich-lyrics provider; sends the same metadata | Public GET without credentials; exact HTTPS host/path, no redirects/proxies, strict metadata match and bounded TTML | 1 MiB response; shared 24-second load deadline |

Catalog and plugin requests allow at most three redirects. Every hop and the
final URL must satisfy the same HTTPS, host, repository, commit, and path policy.
A redirect to a URL that cannot be revalidated fails closed. Responses whose
declared or observed size exceeds the limit are rejected before installation.
The aggregate declared size of one plugin package may not exceed 20 MiB.

The mutable `main` catalog is only an index used to discover new immutable
package revisions. Executed plugin files are pinned to a full commit and are
verified independently by size and SHA-256.

Application updates are checked only against GitHub's latest final release.
Drafts, prereleases, non-semantic tags, duplicate or missing installer assets,
assets without GitHub's `sha256:` digest, and substituted repository URLs fail
closed. A verified installer is staged under `%APPDATA%\Amazify\updates` and is
rechecked immediately before launch. Amazify never installs it silently.

Development source builds may use an explicitly enabled local `file://` catalog.
Frozen production builds must not enable local catalogs from an environment
variable alone.

## Local DevTools Interface

| Interface | Purpose | Authentication and validation | Limit |
| --- | --- | --- | --- |
| `http://127.0.0.1:<selected-port>/json/list` | Discover the Amazon Music page target | Direct loopback request with proxies disabled; listener owner must match the approved Amazon Music process identity | 1 MiB response |
| `ws://127.0.0.1:<selected-port>/devtools/page/<target-id>` | Evaluate and maintain the injected runtime | Direct loopback socket with explicit no-proxy routing; exact scheme, host, port, path, target ID, validated Amazon Music target, and post-connect listener-owner check | DevTools protocol message handling is bounded by command-specific parsing |

The port is selected for the local session and must not use a remote interface.
A title containing "Amazon Music" is insufficient validation. The page URL must
use an approved regional `https://music.amazon.<suffix>` origin or Amazon's
regional `https://www.amazon.<suffix>/morpho/webapp/...` desktop route.
Expected listener identity includes process creation time and a canonical
Amazon Music executable path under the protected `Program Files\\WindowsApps`
package root; a PID alone is not treated as stable identity.

## Local HTTP Bridge

The bridge binds to `127.0.0.1` on a random available port and is not intended to
be reachable from another machine.

| Route | Method | Authentication | Purpose |
| --- | --- | --- | --- |
| `/health` | `GET` | None; returns no plugin or session state | Local liveness probe |
| `/state` | `GET` | `X-Amazify-Token` | Runtime and plugin state |
| `/plugins` | `GET` | `X-Amazify-Token` | Installed plugin metadata |
| `/catalog` | `GET` | `X-Amazify-Token` | Cached or refreshed catalog metadata |
| `/plugins/enable` | `POST` | `X-Amazify-Token` | Enable an installed plugin |
| `/plugins/disable` | `POST` | `X-Amazify-Token` | Disable an installed plugin |
| `/plugins/install` | `POST` | `X-Amazify-Token` | Install a verified catalog package |
| `/command` | `POST` | `X-Amazify-Token` plus command allowlist | Approved runtime operations |

Authenticated requests use an unpredictable per-session token and a maximum
16 KiB JSON request body. Browser requests with an Origin header are accepted
only from exact supported Amazon Music HTTPS origins. The Host header must name
the selected loopback listener. Responses include `Cache-Control: no-store`.
Credentials are compared without early-exit string comparison.

## Native DevTools Binding

`AmazifyNativeCommand` is an in-process DevTools binding, not a network endpoint.
It uses a separate random session nonce, a 16 KiB JSON message limit, and an
explicit command allowlist. The binding is captured privately and removed from
ambient plugin globals before plugins execute.

Application update status, checks, and install starts are native-binding-only
commands. They are not exposed by the localhost HTTP bridge or the plugin bridge
capability. Installer launch additionally requires a trusted user click in the
injected Settings interface.

Karaoke Lyrics provider commands are also native-binding-only and are
reserved for the exact `amazify.karaoke-lyrics` plugin ID. Provider loads run on a
two-worker executor with at most eight outstanding loads and carry cancelable
request keys. Cancellation persists while a request is queued. No Spotify or
Amazon credentials enter the provider chain or lyrics cache. The frozen plugin
API exposes status, load, cancel and clearCache, not arbitrary fetch or OAuth.
See [Karaoke provider details](karaoke-lyrics-provider.md) for cache and parser
limits and public-service availability restrictions.

## Plugin Network Activity

An enabled plugin runs in the Amazon Music renderer. A plugin declaring
`network` may contact destinations chosen by its code and may observe page-level
network behavior. Amazify cannot provide a complete origin sandbox inside the
shared renderer. Review plugin source and trust information before enabling it.

Traffic generated by Amazon Music itself, including playback, account, artwork,
and notification services, is controlled by Amazon and is not listed here.
