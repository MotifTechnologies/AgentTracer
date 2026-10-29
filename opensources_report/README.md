# Open-source management evidence

Baseline date: 2026-10-14 (UTC) · Repository: `MotifTechnologies/motif-agent-tracer-v2`

This folder collects policy and operational documents backed by existing Git and PR approval records.
Git/PR records are the source of truth for approvals, changes, and remediation history.
Previously approved items are considered **complete under Git-based record management**.

## Documents

| Document | Contents | Status |
| --- | --- | --- |
| [OSS selection exclusions](oss-selection-exclusions.md) | Exclusion and hold criteria from the existing checks; how to register actual exclusions | Complete; consolidates existing policy |
| [Approved organizational policy](organization-policy-approved.md) | Policies approved for this repository and links to their approval PRs | Existing policies approved in Git; consolidated document newly written |
| [RACI](raci.md) | Responsibilities based on CODEOWNERS and PR roles | Complete; new operational role matrix subject to document PR review |

Remote main used for the assessment: [`0a620516f706c8d98a21f182ba1a99e6dc4cc988`](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/0a620516f706c8d98a21f182ba1a99e6dc4cc988).

## Items completed through Git-based records

| Item | Completion evidence | Record management |
| --- | --- | --- |
| Version history of accepted licenses and reviewed exceptions | [Check implementation](../.github/scripts/check_licenses.py), [review JSON](../.github/license-reviews/pypdfium2-5.13.0.json), PR #10 and #24 | Commit diffs and approved PRs |
| Repository policy approval | Approval and merge records in PR #10, #24, and #28 | PR records identify the approver, approval date, and reviewed commit |
| Reviewer assignment | [CODEOWNERS](../.github/CODEOWNERS), PR #10 | Path ownership and assignment changes tracked in Git |
| Existing vulnerability exception approvals | [Exception list](../.github/pip-audit-ignore.txt), PR #10 | Review dates, reasons, reassessment criteria, and introducing PR |
| Vulnerability remediation history | PR #18 and #24, dependency lock changes, and CI results | PRs, commits, and repeat scans serve as remediation records |

Evidence PRs: [#10](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/10),
[#18](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/18),
[#24](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/24),
[#28](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/28).

## Evidence retention

| Type | Retention policy | Recorded dates |
| --- | --- | --- |
| This folder, policy code, and notices | Git history | Documents created 2026-10-14 |
| Approval, exception, and remediation records | GitHub PRs, reviews, and commits are the originals | See the PR links above |
| Latest main SBOM artifact at the assessment date | 90 days after generation | Created 2026-10-12 09:42:51 UTC / expires 2027-01-10 09:41:58 UTC |
| Weekly reassessment SBOM artifact at the assessment date | 90 days after generation | Created 2026-10-12 03:14:15 UTC / expires 2027-01-10 03:13:11 UTC |
| Actions runs and vulnerability scan logs | Verify the configured retention period | Check Actions settings |
| Release SBOM | The Release workflow attaches release assets (`agent-tracer-<tag>-sbom.zip`, `.sha256`) when a release is published; no expiration | Check each release |

[Main run recorded in the assessment](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38231561759),
[scheduled run](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38198888339).
Preserve evidence needed for long-term retention before each artifact expires. SBOMs for released commits are retained as release assets.

## Scope

OSS management documents and Git approval history for this repository.

## Document review results

Checked: 2026-10-16 · Content cross-check: Codex.
The following records the comparison of these documents with their original evidence.

- [x] Checked approval and merge records for PR #10, #18, #24, and #28, and compared approvers, dates, and reviewed commits with the policy document.
- [x] Compared selection exclusion rules with the check implementation and review evidence, distinguishing policy rules from actual exclusion cases.
- [x] Reflected the user's choice of per-PR responsible persons and approvers in the RACI, and checked CODEOWNERS plus roles and evidence for all ten activities.
- [x] Documented Git/PR and CI artifact retention, including the 90-day period, creation and actual expiration dates, and long-term preservation procedures.

Record assignments, approvals, and evidence preservation for each activity in its PR or issue according to the
[RACI operational checklist](raci.md#checks-for-each-activity).
