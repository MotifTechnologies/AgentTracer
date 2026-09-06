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
