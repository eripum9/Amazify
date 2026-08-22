# Security Policy

## Supported Versions

Security fixes are made only on the latest commit of `main` and the latest
published version. Older commits, locally modified builds, and third-party
packages are not maintained by the Amazify project.

Candidate artifacts produced by GitHub Actions are test artifacts, not public
releases. They may be deleted or replaced and should not be redistributed as
official builds.

| Version | Security support |
| --- | --- |
| Latest `main` or latest public release | Supported |
| Older commits or releases | Not supported |

## Reporting A Vulnerability

Do not disclose a suspected vulnerability, token, cookie, private plugin,
unredacted log, or exploit details in a public issue.

Submit sensitive reports through [GitHub private vulnerability reporting](https://github.com/eripum9/Amazify/security/advisories/new).
Use a normal [GitHub issue](https://github.com/eripum9/Amazify/issues) only for
non-sensitive hardening suggestions.

Include, where applicable:

- the Amazify version or commit SHA;
- Windows and Amazon Music versions;
- whether the source build, candidate artifact, or local modification was used;
- the plugin ID, version, trust tier, and source commit;
- a minimal reproduction path and expected impact; and
- redacted logs with credentials, bridge tokens, cookies, and personal data removed.

Maintainers will acknowledge private reports as availability permits. Do not
test against another person's account or publish proof-of-concept code before
the report has been triaged.

## System And Scope

Amazify is a local Windows companion that starts or attaches to Amazon Music,
uses a loopback Chromium DevTools endpoint, injects a reversible runtime, and
loads user-selected plugins. This policy covers:

- the Python launcher, daemon, DevTools client, loopback bridge, and native binding;
- plugin discovery, download, verification, installation, and execution;
- local state, logs, shortcuts, packaged executables, and the Inno Setup installer;
- the official catalog and GitHub Actions candidate-build pipeline; and
- security boundaries between Amazify, Amazon Music, plugins, GitHub, and the OS.

Amazon Music, Windows, GitHub, PyPI, Inno Setup, and community plugin
repositories are external dependencies. Their own services and account
security are outside Amazify's control.

## Security Invariants

Security-sensitive code and reviews should preserve these properties:

- DevTools and bridge listeners bind only to loopback interfaces.
- Amazify attaches only to a validated Amazon Music page and matching local
  DevTools listener owned by the expected process tree. Listener identity is
  tied to process creation time and a canonical protected Amazon Music package
  path, then checked again after the WebSocket connects.
- The selected WebSocket scheme, host, port, target path, and target ID must
  match the validated DevTools target. Loopback DevTools traffic must bypass
  ambient HTTP proxy configuration.
- Bridge and native commands require an unpredictable session credential,
  compare credentials without early-exit string comparison, use explicit
  command allowlists, and reject oversized or malformed requests.
- Browser bridge access is limited to exact supported Amazon Music origins.
- Catalog and plugin downloads are bounded, use HTTPS, validate every redirect,
  pin a full Git commit, and verify the declared byte size and SHA-256 before use.
- Application updates accept only the exact official latest final GitHub release,
  require one exact installer asset with GitHub's SHA-256 digest, validate and
  bound every redirect and byte, stage atomically, and reverify before launch.
- Application installation is never silent and cannot be initiated through a
  plugin bridge capability or the localhost HTTP bridge.
- Plugin installation is staged and recoverable; failed updates must not remove
  the last working copy or silently enable a plugin. Plugin IDs must be
  canonical Windows-safe directory names, and every changed package identity
  must be explicitly re-enabled after installation.
- Privileged marketplace actions require a trusted user event. Runtime
  reinjection captures security-sensitive primitives before old plugin cleanup
  runs, and privileged request serialization never returns to mutable globals.
- Workflows use hash-locked dependencies, immutable action SHAs, and least
  privilege. Candidate builds never publish a GitHub release.
- Logs, diagnostics, workflow artifacts, and issue templates must not expose
  Amazon session data, local bridge credentials, or private plugin contents.

See [the threat model](docs/threat-model.md) and
[network endpoint inventory](docs/network-endpoints.md) for the detailed
boundaries and limits.

## Plugin Trust And Permissions

Plugins run in the Amazon Music renderer and can interact with the page. A
malicious plugin may read visible account or playback data, alter the UI,
observe page requests, impersonate user actions, or disrupt playback.

The `dom-read`, `dom-write`, `dom-style`, and `network` permissions are
disclosures and consent signals. They are not a renderer sandbox and cannot
fully isolate JavaScript from the Amazon Music page. Amazify-enforced
capabilities such as bridge state and bridge commands must be exposed only
through a frozen, permission-scoped API.

`stock` means the exact catalog revision was reviewed and tested by the
Amazify project. It does not mean the plugin is harmless or formally audited.
`community` plugins are third-party code and remain disabled after install
until the user explicitly enables them. Review the source commit, requested
permissions, hashes, and author before enabling any plugin.

Security reports involving a documented permission alone are not
vulnerabilities. Permission bypass, undisclosed privileged access, catalog
verification bypass, cross-plugin authority, or access to Amazify secrets is
in scope.

## Local Data And Credentials

Amazify stores state, installed plugins, and logs under `%APPDATA%\Amazify`.
The loopback bridge token and native session nonce are ephemeral and must not be
persisted to logs or exposed to plugins. Amazify does not intentionally read or
export Amazon passwords, cookies, or DRM material.

A process running as the same Windows user can generally inspect that user's
files and may be able to inspect process memory. Amazify does not claim to
protect against a fully compromised Windows account.

## Build And Artifact Trust

The manual candidate workflow builds only the current `main` commit whose
version matches project and installer metadata. It installs checked-in,
hash-locked dependencies; runs tests and security checks; creates checksums,
runtime/build SBOMs, build evidence, and provenance attestations; and uploads a workflow
artifact.

The workflow has no `contents: write` permission and does not create, edit, or
publish GitHub releases. Public release publication requires a separate,
explicit maintainer action that is not part of this repository baseline.

Amazify executables are not Authenticode signed. A checksum detects accidental
or malicious substitution only when the checksum itself comes from a trusted
workflow artifact. GitHub provenance improves traceability but does not make an
unreviewed commit trustworthy.

## Out Of Scope And Residual Risk

- Amazon Music service behavior, DRM, account authorization, and upstream UI changes.
- Malicious software already executing as the same Windows user or administrator.
- Network activity intentionally performed by an enabled plugin within its
  disclosed page-level permissions.
- Availability failures caused by Amazon Music or GitHub changing unsupported interfaces.
- SmartScreen warnings and publisher identity for unsigned local candidate builds.

These exclusions do not excuse an Amazify control bypass. Report cases where
Amazify makes an external risk materially worse or violates an invariant above.
