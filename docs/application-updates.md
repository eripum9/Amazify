# Application Updates

Amazify 1.1.0 includes an application updater for final GitHub releases. It is
separate from the plugin marketplace updater.

## User Flow

- Settings can check for a release automatically when opened.
- `amazify update check` performs the same check from the CLI.
- Installing always requires an explicit Settings confirmation or the CLI's
  interactive confirmation. `--yes` is available for deliberate automation.
- The normal visible Inno Setup installer completes the update and restarts the
  Amazify daemon. The updater never installs an application release silently.

## Accepted Release Contract

The updater accepts a release only when all of these conditions hold:

- GitHub returns it from the exact official `releases/latest` API endpoint;
- it is neither a draft nor a prerelease;
- its tag is exactly `vmajor.minor.patch`;
- its release page belongs to `eripum9/Amazify` and matches the tag;
- it contains exactly one uploaded asset named `AmazifySetup.exe`;
- the asset URL belongs to that exact repository and tag;
- GitHub reports a valid `sha256:` digest and a size no larger than 256 MiB.

The metadata response is limited to 256 KiB and cannot redirect. The installer
can follow no more than three HTTPS redirects, and every destination must be
either the exact release URL or an approved GitHub release-asset host. The
download is bounded to its advertised size, streamed to a unique staging file,
atomically renamed, and reverified immediately before execution.

## Maintainer Release Requirements

Before publishing a release, build and test the matching candidate from current
`main`. All five version sources must match without a `v` prefix:

- `pyproject.toml`;
- `amazify/__init__.py`;
- `packaging/Amazify.iss`;
- `packaging/amazify_installer.py`;
- `packaging/Amazify.version`.

Publish the final release with tag `v<version>` and upload the candidate's exact
`AmazifySetup.exe` as a release asset. Do not rename it. Confirm the GitHub API
reports the same SHA-256 as the candidate's `SHA256SUMS.txt` before announcing
the release.

Candidate workflow artifacts are intentionally not releases and cannot be seen
by the updater. No release is created automatically by this repository.
