## What this changes

<!-- The behaviour that differs afterwards, not a list of edited files. -->

## Why

<!-- The problem. Link the issue if there is one. -->

## Checklist

- [ ] `uv run pytest` passes locally
- [ ] `uv run ruff check src tests` and `uv run ruff format --check src tests` are clean
- [ ] No `confidential/`, `DATA_BUILDER/`, real `.env`, or generated artefact is in the diff
- [ ] New dependencies are compatible with Apache-2.0 (CI checks; see CONTRIBUTING.md)
- [ ] `uv.lock` is committed alongside any `pyproject.toml` change
- [ ] `NOTICE` still credits Stirrup if you touched attribution
