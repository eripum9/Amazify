# Dependency Management

## Files

- `requirements-runtime.in` contains exact direct runtime dependencies.
- `requirements-dev.in` adds exact CI, test, audit, lint, and type-check tools.
- `requirements-build.in` adds exact packaging and SBOM tools.
- `requirements.txt`, `requirements-dev.lock`, and
  `requirements-build.lock` are generated, hash-locked environments.

`pyproject.toml` retains compatible package metadata for source installation.
CI and candidate builds do not resolve those ranges; they install a checked-in
lock with `--require-hashes` and binary distributions only.

## Regenerating Locks

Use CPython 3.12.10 on Windows and the `pip-tools` version pinned in
`requirements-build.in`. Regenerate all three locks in one change:

```powershell
$python = "C:\path\to\python-3.12.10.exe"
& $python -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --resolver=backtracking --no-emit-index-url --no-emit-trusted-host --newline=lf --output-file requirements.txt requirements-runtime.in
& $python -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --resolver=backtracking --no-emit-index-url --no-emit-trusted-host --newline=lf --output-file requirements-dev.lock requirements-dev.in
& $python -m piptools compile --quiet --allow-unsafe --generate-hashes --strip-extras --resolver=backtracking --no-emit-index-url --no-emit-trusted-host --newline=lf --output-file requirements-build.lock requirements-build.in
```

Review direct and transitive changes, then verify:

```powershell
& $python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
& $python -m pip_audit -r requirements.txt --strict
& $python -m pip_audit -r requirements-build.lock --strict
& $python -m pytest tests --cov=amazify --cov-report=term-missing --cov-fail-under=45
```

Do not hand-edit generated locks. Dependabot proposes input and lock updates;
the same review and verification requirements apply.
