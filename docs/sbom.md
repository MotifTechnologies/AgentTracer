# Python SBOM and license policy

The Security workflow's `licenses` job generates CycloneDX 1.6 JSON inventories
on pull requests, main pushes, scheduled runs and manual dispatch. It checks
license declarations and preserves evidence even if a policy check fails.

## Coverage

- `runtime.cdx.json`: the project's locked runtime environment, excluding dev
  and compliance tools.
- `development.cdx.json`: runtime plus dev dependencies, excluding the
  CycloneDX tool environment.
- `mcp-<server>.cdx.json`: each packaged stdio MCP server's PEP 723 environment,
  resolved from its adjacent `server.py.lock`. No server or agent is executed.
- External HTTP MCP services are named in `index.json` as outside this scan.

The builder uses separate environments so scanner dependencies do not silently
appear in the runtime inventory. CycloneDX gathers available license texts.
`index.json` records the Git revision, Python and scanner versions, lock hashes,
SBOM hashes and whether generation completed. The uploaded artifact contains
only reports and resolved requirements, never environments or credentials.
Actions artifacts are retained for 90 days; archive the final reports with
release evidence before they expire. This workflow does not publish a release.

## Run locally

```bash
uv sync --locked --dev --group compliance
uv run --no-sync python .github/scripts/build_sbom.py
uv run --no-sync python .github/scripts/check_licenses.py sbom/*.cdx.json --report sbom/license-report.json
```

After changing a packaged server's inline dependencies, update its lock:

```bash
uv lock --script src/agent_tracer/mcp_servers/pdf/server.py
```

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
