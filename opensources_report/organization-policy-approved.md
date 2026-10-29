# Approved organizational open-source policy — repository scope

Document ID: OSS-POL-001 · Consolidated version: 1.1 · Created: 2026-10-14 · Updated: 2026-10-16

Status: **Existing policies approved in Git / this consolidated document newly written**.

This document consolidates policies approved and merged in `MotifTechnologies/motif-agent-tracer-v2`.
The original approval evidence is the review, reviewed commit, and merge record in each PR below.

## Original approval records

All times are UTC.

| Policy scope | Approval record | Approver | Approval time | Merge time | Reviewed commit |
| --- | --- | --- | --- | --- | --- |
| CI, license checks, vulnerability exceptions, contribution controls, and assigned reviewers | [PR #10](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/10) | `gihuncho` | 2026-09-07 02:37:15 | 2026-09-09 03:06:48 | `529e36f1655aa922ad8625ef4a1f49bafe60aed8` |
| SBOM generation, license policy checks, and PDF wheel review | [PR #24](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/24) | `junhyeok-motech` | 2026-10-07 01:45:43 | 2026-10-07 01:46:16 | `d80e06599fbedef6cb5e9359d256a53c1c783307` |
| SBOM evidence retention, interpretation, and dependency review maintenance | [PR #28](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/28) | `junhyeok-motech` | 2026-10-12 05:15:24 | 2026-10-12 05:16:14 | `79598c560c255e9ba0e948451ce0b1e7ba32602f` |

## Applicable policies

1. **Selection and license verification**: Check dependency versions, declarations, and distributed license texts. The [check implementation](../.github/scripts/check_licenses.py) defines accepted identifiers and exact SPDX expression evaluation. Review evidence before approving an unidentified declaration.
2. **Review evidence**: Bind individual reviews to actual versions, files, and hashes. Reassess when texts or versions change. Also check the [selection exclusions](oss-selection-exclusions.md).
3. **Reproducibility and identification**: Pin root dependencies in `uv.lock` and MCP dependencies in adjacent `server.py.lock` files. Link SBOMs to commits and input/output hashes.
4. **Vulnerability management**: Scan root runtime dependencies with `pip-audit`. Existing accepted exceptions are approved and managed through the [exception list](../.github/pip-audit-ignore.txt) and PR #10. Track exception changes and fixes through PRs and repeat scans.
5. **Change approval and roles**: Use reviewers assigned in [CODEOWNERS](../.github/CODEOWNERS) and PR approval records. Merge after approval, required checks, and conversation resolution under the applicable branch rules.
6. **Distribution notices**: Maintain [LICENSE](../LICENSE) and [NOTICE](../NOTICE). When distributing the PDF environment, check the [wheel review](../docs/pypdfium2-license-review.md), including full notices and acknowledgment requirements.
7. **Scheduled checks**: Run Security checks for PRs, main pushes, every Monday at 03:00 UTC, and manual dispatches. [SECURITY.md](../SECURITY.md) and the [workflow](../.github/workflows/security.yml) define the procedures.
8. **Retention**: Manage policies, lists, approvals, and remediation records in Git/PRs. Retain SBOM and license result artifacts for 90 days, preserving required final evidence separately before expiration. See the [retention inventory](README.md#evidence-retention) for dates.

## Recognizing approval, exception, and remediation history

An approved PR linked to a change constitutes **completed approval-history management** for that scope.
Use Git diffs for document, list, and lock changes; reviews for approval; merge commits for application;
and the corresponding CI runs for validation results.

Record approvals for new exceptions, policies, and document changes in their PRs.

## Scope and changes

This policy applies to development and distribution management in this repository.
Review Docker/OS packages, binaries inside wheels, external services, and data/API rights individually.
Review changes to scope, procedures, and [RACI](raci.md) in the relevant PR and link their approval records.
