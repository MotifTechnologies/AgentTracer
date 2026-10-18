# Contributing

Thanks for taking the time. This is an Apache-2.0 project built on
[Stirrup](https://github.com/ArtificialAnalysis/Stirrup); see `NOTICE`.

All participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and proposing changes

Search existing issues and pull requests before opening a new one. Use the
[issue templates](https://github.com/MotifTechnologies/motif-agent-tracer-v2/issues/new/choose)
for bug reports and feature requests. For a bug, include a minimal
reproduction, expected and actual behavior, and your environment. For a
feature, describe the problem, proposed behavior, and alternatives.

Remove API keys, private datasets, and other sensitive information from
configuration snippets, logs, and trajectories before sharing them. Report
security vulnerabilities privately using [SECURITY.md](SECURITY.md), rather
than through an issue.

For a substantial change, open an issue first so maintainers can discuss the
scope and approach. Small fixes and documentation improvements can go
directly to a pull request.

## Getting set up

Install Python 3.13 or newer and `uv`, then clone the repository (or your fork)
and enter its directory.

```bash
uv sync              # runtime + dev tools, resolved from uv.lock
uv run pytest -q     # no Docker needed
uvx pre-commit install   # optional; installs the pre-commit hook
```

Docker is only needed to *run* an agent, not to test the code — the suite fakes
the sandbox. `cp .env.sample .env` and fill in `VLLM_API_KEY` when you want to
run one for real.

## Opening a pull request

1. Create a branch from the latest `main`. Use a fork if you do not have
   permission to push a branch to this repository.
2. Keep the change focused. Update documentation and add or update tests
   when behavior changes.
3. Run the applicable checks below. For documentation-only changes, check
   links and formatting; explain any skipped checks in the pull request.
4. Commit and push your branch, then open a pull request targeting `main`.
   Fill out the template with the problem, resulting behavior, related
   issues, and validation results.
5. Address review feedback and resolve required CI failures before merge.

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

## Automatic merging and merge queue

Non-draft pull requests targeting `main` are enrolled in GitHub auto-merge when
opened, reopened, marked ready, updated with commits, or edited. Once the merge
queue rule is active, eligible PRs enter the queue after one code-owner approval,
all nine required checks, and resolved review conversations. Authors cannot
approve their own PRs.

After an approval or a successful PR check workflow, automation rechecks open PRs
with auto-merge enabled and queues eligible entries that have not entered the
queue. A scheduled reconciliation runs every ten minutes as a fallback (GitHub
may delay scheduled runs), and maintainers can run **Auto-merge** manually from
Actions. Reconciliation preserves manually disabled auto-merge and skips drafts,
unapproved PRs, pending or failed required checks, and entries already queued.

The queue tests a temporary commit containing the PR, current `main`, and any
earlier queued changes. All nine checks run again on `merge_group` events; the
contribution guard compares the entire group against its base SHA. GitHub merges
passing entries with a merge commit. This removes the need to repeatedly click
**Update branch** solely because another PR merged. Conflicts and failed checks
remove an entry from the queue for correction; review-invalidating changes still
need another approval. Until the queue rule is activated, the existing strict
up-to-date requirement still applies.

Keep unfinished work as a draft. Automation does not resolve conflicts, submit
approvals, or bypass repository rules. Disabling auto-merge manually lasts until
the next qualifying event above; use a draft to pause enrollment.

The repository's **Allow auto-merge** setting must stay enabled. The
`auto-merge.yml` workflow uses the built-in GitHub token and only calls GitHub
APIs; it never checks out or runs pull-request code.
The **PR approval** workflow only signals a review with no token permissions.
Privileged reconciliation runs from the default branch via `workflow_run`, reads
live PR state, and uses GitHub's native queue API with an expected-head check.

An administrator must activate the prepared
[main merge queue ruleset](https://github.com/MotifTechnologies/motif-agent-tracer-v2/rules/24909551)
only after all three required-check workflows support `merge_group` on `main`.
Keep the existing `main` ruleset active. Use merge commits,
require every queue entry to pass its checks, build and merge one PR at a time,
and allow 30 minutes for checks. Keep the existing code-owner, review-resolution,
required-check, and no-bypass rules. GitHub's
[merge queue guide](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
describes the temporary branches and queue operation.

## Commits and history

Write commit subjects in the imperative, and say why in the body. Formatting-only
changes go in their own commit; add the SHA to `.git-blame-ignore-revs`, and run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame`
skips them.
