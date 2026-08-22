# Windows Candidate Builds

The `Build Windows Candidate` workflow is a manual, non-publishing build used
for maintainer testing. It does not create a tag, draft, release, or public
installer entry.

## Source Requirements

- Dispatch the workflow from `main` with a `major.minor.patch` version.
- The checked-out commit must still equal the current remote `main` commit.
- The input version must match `pyproject.toml`, `amazify/__init__.py`, the
  PyInstaller-facing packaging metadata, and `packaging/Amazify.iss`.
- The workflow rechecks remote `main` before uploading evidence.

Workflow input is passed through step environment variables and validated
before shell use. It is never interpolated directly into a `run` script.

## Build And Verification

The workflow uses Windows 2025, CPython 3.12.10, the checked-in build lock with
`--require-hashes`, and Inno Setup 6.7.3. It runs compilation, pytest with at
least 45% core-package coverage, workflow contract tests, Ruff, Pyright,
dependency audits, PyInstaller packaging, executable smoke tests, and a silent
installer/uninstaller cycle.

PyInstaller runs with UPX disabled. An unrelated `upx.exe` present on a runner
or developer machine is therefore not allowed to alter the packaged binaries.

The installer smoke uses `/CI-SMOKE` and an isolated directory under
`RUNNER_TEMP`. That mode suppresses startup registration, shortcuts, PATH
changes, daemon launch/stop hooks, and deletion of existing user shortcuts.

## Evidence

Successful runs produce an Actions artifact containing:

- `amazify.exe`, the `amazifyw` directory, and `AmazifySetup.exe`;
- `SHA256SUMS.txt`;
- reproducible CycloneDX JSON inventories for runtime dependencies and the
  locked build environment;
- a build manifest with version, commit, runner, Python, Inno Setup, and hashes;
- a security report summarizing completed checks; and
- GitHub build provenance attestations for distributable binaries and checksums.

Microsoft Defender scans the output when Defender is available on the hosted
runner. An unavailable Defender service is recorded in evidence rather than
misreported as a passing scan.

Artifacts uploaded by this workflow are unsigned test candidates. Publishing a
release is a separate process and must be explicitly authorized outside this
workflow.

## Runner Assumptions

The workflow assumes GitHub's hosted `windows-2025` image is x64, has a current
Actions runner capable of executing Node 24 actions, provides `winget`, and can
reach GitHub, PyPI, and the Windows Package Manager source. It installs and then
verifies Inno Setup 6.7.3 rather than trusting a preinstalled compiler.

Artifact attestation must be available for the repository and workflow token.
Microsoft Defender is best-effort because hosted image policy can disable its
service; an unavailable scan is recorded as `unavailable`, never as `passed`.
