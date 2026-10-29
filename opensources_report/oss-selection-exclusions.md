# OSS selection exclusions

Document ID: OSS-SEL-001 · Version: 1.1 · Created: 2026-10-14 · Updated: 2026-10-16

Scope: Python dependencies and packaged stdio MCP environments in this repository.
The table summarizes decisions made by the [existing license checker](../.github/scripts/check_licenses.py)
for use when selecting dependencies.

## Exclusion and hold criteria

| ID | Condition | Selection decision | Evidence and conditions for reconsideration |
| --- | --- | --- | --- |
| EX-01 | A valid SPDX expression does not evaluate to an accepted license (`blocked`) | Exclude under the current policy | Check for an exact `OR` expression with an accepted alternative. Policy changes require an approved PR with evidence, code, and tests |
| EX-02 | Missing, unrecognized, or custom declaration, including `LicenseRef` (`unknown`) | Hold adoption pending evidence | Review distributed texts, versions, and terms; add evidence through the existing hash-based review process |
| EX-03 | An `AND` operand is disallowed, or a `WITH` combination is not approved | Exclude or hold for reassessment | Review all combined conditions and verify compliance |
| EX-04 | Unreviewed pypdfium2 version, platform, or declaration; missing, added, duplicated, or changed notice files | Do not apply the existing special-case review | Reassess all notice files and distribution obligations; record the exact filename/SHA-256 set in the approval PR |
| EX-05 | Missing MCP script lock, an unsupported launch format that cannot be scanned, or an incomplete SBOM | Hold adoption until verification is complete | Complete locks and collection coverage, then confirm a complete SBOM and passing checks |

For example, `GPL-3.0-only` is blocked because it is absent from the accepted list.
A valid expression recognized by the checker can pass if it includes an accepted alternative,
as in `MIT OR GPL-3.0-only`.

## Relationship to accepted licenses and individual reviews

| Category | Managed item | Evidence |
| --- | --- | --- |
| Accepted list | Exact SPDX identifiers in `ACCEPTED` | [Check implementation](../.github/scripts/check_licenses.py) |
| Mapping after text review | python-dateutil 2.9.0.post0's `Dual License` declaration | `REVIEWED_TEXTS` in the same code, version, and text SHA-256 |
| Individual notice-bundle review | pypdfium2 5.13.0, reviewed Linux x86_64 / Windows x64 wheels | [Review](../docs/pypdfium2-license-review.md), [file hashes](../.github/license-reviews/pypdfium2-5.13.0.json) |
| Accepted vulnerability exceptions | Pillow-related exception identifiers | [pip-audit-ignore.txt](../.github/pip-audit-ignore.txt); separate from license exclusions |

Some LGPL and MPL identifiers are also in `ACCEPTED`.
Check the relevant review and original texts for distribution notices and source-provision requirements.

## Actual exclusion register

Assessment as of 2026-10-14: no individual exclusion cases registered.

| Case ID | OSS / version / purpose | Applicable criterion | Review result | Approval / decision PR | Reassessment conditions |
| --- | --- | --- | --- | --- | --- |
| Not registered | No confirmed actual exclusion case | Not applicable | Unconfirmed | Not applicable | Register when a case occurs |

For each actual case, record the package and version, exclusion reason, review date and owner,
alternative, and reassessment conditions in its PR, then link it from this table.

## Changes and reassessment

- Existing policy history: [initial introduction](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/bd86549), [SBOM policy improvements](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/24af3fe), [wheel review](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/d80e065).
- Run automatic checks every Monday at 03:00 UTC and when dependencies or license evidence change.
- For selection reassessment, record suitability for the intended use, alternatives, and changed conditions in the case PR.
- Keep individual review records for OS utilities, external services, and data/API rights.
