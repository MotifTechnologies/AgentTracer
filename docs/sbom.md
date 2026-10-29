# Python SBOM and license policy

The Security workflow's `licenses` job generates CycloneDX 1.6 JSON inventories
on pull requests, main pushes, scheduled runs and manual dispatch. It checks
license declarations and preserves evidence even if a policy check fails.

A software bill of materials (SBOM) is the inventory of software components,
versions, licenses and dependency relationships for a particular build environment.
CycloneDX is the format used to exchange that inventory; it is not the policy
checker. Here, `build_sbom.py` generates the inventory and `check_licenses.py`
applies the repository's license policy. The separate `pip-audit` job checks known
vulnerabilities in the root project's runtime dependencies.

## Coverage

- `runtime.cdx.json`: the project's locked runtime environment, excluding dev
  and compliance tools.
- `development.cdx.json`: runtime plus dev dependencies, excluding the
  CycloneDX tool environment.
- `mcp-<server>.cdx.json`: each packaged stdio MCP server's PEP 723 environment,
  resolved from its adjacent `server.py.lock`. No server or agent is executed.
- External HTTP MCP services are named in `index.json` as outside this scan.

With the current eight packaged stdio servers, each complete run produces ten
SBOMs. Discovery is based on the repository's packaged manifests, not a user's
custom `mcp.discovery_dir` or the subset selected for one agent run.

The builder uses separate environments so scanner dependencies do not silently
appear in the runtime inventory. CycloneDX gathers available license texts.
`index.json` records the Git revision, Python and scanner versions, lock hashes,
SBOM hashes and whether generation completed. The uploaded artifact contains
only reports and resolved requirements, never environments or credentials.
Actions artifacts are retained for 90 days. For a release, the Release
workflow attaches the same report set to the release itself (see below), where
it does not expire.

## Release assets

Publishing a GitHub release runs the **Release** workflow at the release tag.
It repeats the `licenses` job's steps and attaches two files to the release:

- `agent-tracer-<tag>-sbom.zip`: every `*.cdx.json`, `mcp-*.requirements.txt`,
  `index.json` and `license-report.json` from that run.
- `agent-tracer-<tag>-sbom.zip.sha256`: its checksum, for `sha256sum -c`.

If the license check fails, nothing is attached and the run fails. The reports
are still kept as that run's `release-sbom-<tag>-<attempt>` artifact. To attach
or replace the set on an existing release, run the workflow manually with the
tag; uploads overwrite files of the same name.

## Download and interpret a CI report

Open the repository's **Actions → Security** workflow, select the run for the
code revision you are reviewing, and download the artifact named
`python-sbom-<github.sha>-<run_attempt>` from its summary. Check `index.json`'s
`commit` rather than assuming it equals the PR head: a pull-request run may use
GitHub's temporary merge revision. For a released commit, use the release
assets. For any other merged commit, use the `main` push run, or manually
dispatch the workflow at the appropriate ref.

| File | What to check or share with an OSS reviewer |
| --- | --- |
| `*.cdx.json` | Component names, exact versions, declarations and available license texts for each environment. |
| `index.json` | Scanned commit, tool versions, input/lock and SBOM SHA-256 hashes, excluded services, and `complete` generation status. |
| `license-report.json` | Overall `passed`, SBOM `errors`, per-component `verdict` and original/normalized declarations. Reviewed bundles also include the review reference and observed file hashes. |
| `mcp-*.requirements.txt` | The resolved dependency list used to install each MCP environment. |

`allowed` means the recorded declaration or exact reviewed evidence satisfies
repository policy. `unknown` requires evidence review; `blocked` identifies a
policy-disallowed expression. Neither a green job nor an `allowed` component
automatically fulfills redistribution obligations.

A failed job may still have useful artifacts. Require `index.json.complete: true`,
all expected SBOMs, and `license-report.json.passed: true` for a complete accepted
inventory. If installation/generation fails, some outputs or the policy report
may be absent; consult the job logs rather than treating a partial artifact as a
pass. Archive the report set with its commit before the 90-day retention expires.

## Run locally

The following commands use Bash from the repository root. Use the workflow's
configured uv version (`0.12.22`) when reproducing its environment.

```bash
uv sync --locked --dev --group compliance
uv run --no-sync python .github/scripts/build_sbom.py
uv run --no-sync python .github/scripts/check_licenses.py sbom/*.cdx.json --report sbom/license-report.json
```

Generated files and environments under `sbom/` are ignored by Git. Keep reports
as evidence; commit manifests, locks and reviewed policy inputs instead.

## Changing dependencies and review evidence

For a root-project dependency, use `uv add` or update the existing lock entry:

```bash
uv lock --upgrade-package <package>
```

Commit the resulting `uv.lock` and any changed `pyproject.toml`. A root lock
update does not update MCP script locks.

After changing a packaged server's inline dependencies, update its lock:

```bash
uv lock --script src/agent_tracer/mcp_servers/pdf/server.py
```

To update an already locked script dependency, add `--upgrade-package <package>`
to that command. Commit the affected `server.py`/`server.py.lock` changes, run the
relevant tests, and regenerate/check all SBOMs. Fixing a runtime vulnerability
also requires rerunning `pip-audit`; a license pass does not imply a vulnerability pass.

If a declaration is `unknown`, inspect the installed package's actual license
files and applicable distribution conditions. Record the source/version,
decision, limitations and obligations in a review document. If a file-backed
bundle rule is appropriate, the collector must include its complete notice
directory and the review JSON in `.github/license-reviews/` must pin the exact
name, version, declaration and whole filename/SHA-256 set. Review every new or
changed file before changing the pinned set; do not copy hashes from a failed run
without inspecting the evidence. The report preserves the original declaration
and references the review rather than guessing a single SPDX license for the bundle.

The current pypdfium2 5.13.0 review covers the inspected Linux x86_64 and Windows
x64 notice sets. Missing, extra, duplicate or changed files, another declaration,
version or an unreviewed platform fail closed. Update the associated review
document and regression tests together with any deliberate policy-rule change.

All manifests are discovered on each build. A new stdio launch mechanism or a
missing script lock fails rather than silently reducing coverage. Script locks
also pin subsequent `uv run server.py` executions. Installation and scanning
may access the configured package index; no code or reports are sent to a
third-party compliance SaaS.

## Policy and interpretation

The checker preserves the prior permissive/weak-copyleft dependency policy,
with exact SPDX identifiers and a real expression parser. It rejects missing
declarations, unrecognized/custom expressions and disallowed expressions.
An `OR` passes if an allowed alternative exists; all terms of an `AND` must
pass. `WITH` exceptions require an explicitly approved whole expression.
Multiple separate license entries are not silently treated as alternatives.

Legacy classifiers and exact known names are retained in the report. A BSD
classifier identifies only a family, not a license variant. Generated full
text attachments are evidence, not independently guessed SPDX identifiers;
an attachment alone cannot pass the gate. A pass means that the available
declarations satisfy policy, not that all distribution obligations are met.

`python-dateutil`'s generic `Dual License` metadata has a version-specific
mapping backed by the SHA-256 of the inspected distributed LICENSE; a changed
version or text requires review. The PDF MCP's `pypdfium2` dependency retains
its original composite declaration. Its complete installed notice directory
is attached to the SBOM and compared against the exact reviewed version and
file hash sets. Changed or incomplete evidence fails the gate. See
[the wheel review and distribution obligations](pypdfium2-license-review.md).

Docker/OS packages, binaries bundled inside wheels, copied source licenses,
external services, seed data and generated dataset/API rights are outside this
Python metadata scan. A source/image scanner and distribution-specific review
are needed for those scopes. In particular, installing or distributing a GPL
OS utility does not by itself determine the license of the framework.
