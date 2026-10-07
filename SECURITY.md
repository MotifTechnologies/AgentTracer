# Security policy

## Reporting a vulnerability

Do not open a public issue. Report privately through GitHub's
[security advisories](../../security/advisories/new), or email
junhyeok.lee@motiftech.io. Expect an acknowledgement within three working days.

## What this project does with untrusted input

`agent-tracer` runs model-authored code. That is the product, not a bug, so it
matters where the boundary is:

- **`environments/docker.py` is the isolation.** Each task gets its own
  container; `code_exec` runs inside it and the sandbox-bound MCP servers
  `attach()` in for the length of a call.
- **`environments/local.py` has no isolation** and says so in its docstring. It
  executes model output on the machine running the tracer, with a shell. It is
  for development. Never point it at anything you would not hand a shell to.

A report that `local.py` runs arbitrary commands is not a vulnerability. A
report that something escapes `docker.py` is.

## Secrets

`.env` is untracked; `.env.sample` is tracked and must hold empty keys only.
CI enforces both, and scans the full history with gitleaks on every PR.

## Dependencies and SBOM evidence

The Security workflow runs on pull requests, pushes to `main`, Mondays at 03:00 UTC,
and manual dispatch. `pip-audit` checks the project's locked runtime dependency set
against known vulnerabilities, applying the documented exceptions in
`.github/pip-audit-ignore.txt`. It does not audit each independent MCP script environment.

The separate `licenses` job inventories the runtime, development environment and
packaged stdio MCP script environments as CycloneDX SBOMs, then checks their license
declarations against repository policy. Its artifact preserves SBOMs, license
results and generation evidence for 90 days, including available reports on failure.
See [the SBOM guide](docs/sbom.md) for download instructions and failure handling.

License policy acceptance and a vulnerability scan cover different questions. Neither
verifies sandbox isolation, dataset/API rights, general Docker/OS packages or all code
inside bundled binaries. The PDF MCP's reviewed pypdfium2 wheel notices are collected
and checked explicitly; [its review](docs/pypdfium2-license-review.md) records the
distribution obligations that remain when shipping that environment.
