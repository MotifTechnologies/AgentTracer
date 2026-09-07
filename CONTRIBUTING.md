# Contributing

Thanks for taking the time. This is an Apache-2.0 project built on
[Stirrup](https://github.com/ArtificialAnalysis/Stirrup); see `NOTICE`.

## Getting set up

```bash
uv sync              # runtime + dev tools, resolved from uv.lock
uv run pytest -q     # 206 tests, ~4 seconds, no Docker needed
uv run pre-commit install   # optional; runs the fast checks before each commit
```

Docker is only needed to *run* an agent, not to test the code — the suite fakes
the sandbox. `cp .env.sample .env` and fill in `VLLM_API_KEY` when you want to
run one for real.

## Run the gates before you push

Everything CI blocks on, you can run locally in about half a minute:

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
uv run python .github/scripts/check_licenses.py
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
| `licenses` | A dependency whose licence is incompatible with Apache-2.0 |
| `secrets` | A credential anywhere in the history, not just the tip |
| `guard` | Confidential paths, real `.env` files, oversized files |
| `typecheck` | A new mypy error in `src/` |

`pip-audit` runs against `uv.lock`, not against whatever happens to be
installed. Vulnerabilities we cannot fix are listed with a reason in
`.github/pip-audit-ignore.txt` — today that is 18 pillow advisories held
back by `moviepy 2.2.1`, which pins `pillow<12.0`. Add to that file only
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
licence stops the build until a human classifies it in
`.github/scripts/check_licenses.py`.

**`src/agent_tracer/mcp/provider.py`.** The `stirrup.tools.mcp` import sits
below `_mcp2_compat.apply()` and carries `# noqa: E402, I001`. It must stay
there — hoisting it to the top of the import block breaks the shim silently.

**`environments/local.py`** has no isolation, on purpose, and its `shell=True`
carries `# nosec B602`. Real isolation is `environments/docker.py`. See
`SECURITY.md`.

## Commits and history

Write commit subjects in the imperative, and say why in the body. Formatting-only
changes go in their own commit; add the SHA to `.git-blame-ignore-revs`, and run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame`
skips them.
