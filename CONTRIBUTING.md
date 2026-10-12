# Contributing

Thanks for taking the time. This is an Apache-2.0 project built on
[Stirrup](https://github.com/ArtificialAnalysis/Stirrup); see `NOTICE`.

## Getting set up

```bash
uv sync              # runtime + dev tools, resolved from uv.lock
uv run pytest -q     # no Docker needed
uv run pre-commit install   # optional; runs the fast checks before each commit
```

Docker is only needed to *run* an agent, not to test the code — the suite fakes
the sandbox. `cp .env.sample .env` and fill in `VLLM_API_KEY` when you want to
run one for real.

## Run the gates before you push

Run the code and security checks locally before pushing. SBOM generation installs
separate environments and may take longer on a cold cache. The commands below use Bash.

```bash
uv run ruff check src tests          # lint
uv run ruff format --check src tests # formatting
uv run pytest -q                     # tests
uv lock --check                      # uv.lock matches pyproject.toml
uv run mypy                          # types
uv run bandit -c pyproject.toml -r src -q --severity-level medium
uv export --no-emit-project --format requirements-txt --no-dev -o requirements-audit.txt
grep -oE '^(PYSEC|GHSA|CVE)-[A-Za-z0-9.-]+' .github/pip-audit-ignore.txt \
  | sed 's/^/--ignore-vuln=/' \
  | xargs uv run pip-audit --strict -r requirements-audit.txt
uv sync --locked --dev --group compliance
uv run --no-sync python .github/scripts/build_sbom.py
uv run --no-sync python .github/scripts/check_licenses.py sbom/*.cdx.json --report sbom/license-report.json
```

`uv run ruff format src tests` fixes formatting; `ruff check --fix` fixes most
lint findings.

## What CI blocks a PR on

| Check | What it stops |
|---|---|
| `lint` | Unformatted code, unused imports, unsorted imports |
| `test` | Regressions |
| `lock` | A `pyproject.toml` change whose `uv.lock` was never regenerated — that is how an unresolved, unaudited dependency reaches `main` |
| `bandit` | New HIGH/MEDIUM security findings in `src/` |
| `pip-audit` | A dependency with a known CVE |
| `licenses` | A Python dependency with a missing, unidentified or policy-disallowed license declaration; missing MCP script locks |
| `secrets` | A credential anywhere in the history, not just the tip |
| `guard` | Confidential paths, real `.env` files, oversized files |
| `typecheck` | A new mypy error in `src/` |

`pip-audit` runs against `uv.lock`, not against whatever happens to be
installed. Vulnerabilities we cannot fix are listed with a reason in
`.github/pip-audit-ignore.txt`; consult that file and the current audit report
for the affected versions and advisories. Add to that file only
when upstream leaves no fix, and delete entries as soon as one lands.

`typecheck` runs mypy over `src/` and blocks like the rest. It is clean; keep
it that way. Where a value is guaranteed by a Pydantic validator that mypy
cannot see, narrow it explicitly rather than reaching for `# type: ignore` —
`get_dataset` in `datasets/custom.py` and the transport branches in
`mcp/discovery.py` are the pattern to copy.

## Rules specific to this repository

**Never commit these.** `.gitignore` lists them, but `git add -f` walks past it,
so CI checks the diff directly:

- `confidential/` — government-programme documents and internal specs
- `DATA_BUILDER/`, `results/`, `datasample/`, `*.pptx` — generated
- any real `.env`. `.env.sample` is tracked and must list **keys with empty
  values only** — it is the one `.env`-shaped file a secret can ride in on

**Attribution.** `NOTICE` and `LICENSE` carry Apache-2.0 §4(d) obligations for a
Stirrup derivative. Changes there need an explicit review, and CI flags them.

**Dependencies.** Add with `uv add`, and commit `uv.lock` in the same commit.
Strong copyleft (GPL, AGPL, SSPL) is blocked. An SPDX `OR` expression passes
when any option is acceptable — `tld` ships
`MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later` and is fine. An unrecognised
licence stops the build until it is reviewed. The SPDX parser preserves
parentheses and `AND`/`OR`/`WITH`, and matches exact identifiers. The gate
enforces the repository's dependency policy, not a legal compatibility opinion.
See [the SBOM workflow](docs/sbom.md) for scope, artifacts and limitations.

For packaged MCP servers, inline PEP 723 dependencies have independent
`server.py.lock` files. Regenerate and commit the affected script lock after a
dependency edit; updating only the root `uv.lock` does not update these environments.
The [MCP development guide](src/agent_tracer/mcp_servers/README.md#의존성-고정과-sbom) describes
the server layout; [SBOM maintenance](docs/sbom.md#changing-dependencies-and-review-evidence)
lists the commands and review procedure. An unrecognised license is resolved by
reviewing its actual evidence, not by adding a blanket ignore. The reviewed
[pypdfium2 wheel](docs/pypdfium2-license-review.md) is a version/file-hash-scoped case.

**`src/agent_tracer/mcp/provider.py`.** The `stirrup.tools.mcp` import sits
below `_mcp2_compat.apply()` and carries `# noqa: E402, I001`. It must stay
there — hoisting it to the top of the import block breaks the shim silently.

**`environments/local.py`** has no isolation, on purpose, and its `shell=True`
carries `# nosec B602`. Real isolation is `environments/docker.py`. See
`SECURITY.md`.

## Automatic merging

Non-draft pull requests targeting `main` are enrolled in GitHub auto-merge when
opened, reopened, marked ready, updated with commits, or edited. GitHub merges
them with a merge commit only after all repository rules pass: one code-owner
approval, all nine required checks, resolved review conversations, and an
up-to-date branch without merge conflicts. Authors cannot approve their own PRs.

An approval alone is not enough when a branch is behind `main`: update it and
wait for CI again. Changes that invalidate an approval need another review.
Keep unfinished work as a draft. Auto-merge does not update branches, resolve
conflicts, submit approvals, or bypass repository rules. Disabling auto-merge
manually lasts until the next qualifying event above; use a draft to pause it.

The repository's **Allow auto-merge** setting must stay enabled. The
`auto-merge.yml` workflow uses the built-in GitHub token and only calls GitHub
APIs; it never checks out or runs pull-request code.

## Commits and history

Write commit subjects in the imperative, and say why in the body. Formatting-only
changes go in their own commit; add the SHA to `.git-blame-ignore-revs`, and run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame`
skips them.
