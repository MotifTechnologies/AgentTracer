# Open-source management RACI

Document ID: OSS-RACI-001 · Version: 1.4 · Created: 2026-10-14 · Updated: 2026-10-16

Scope: OSS management activities in `MotifTechnologies/motif-agent-tracer-v2`.
Operating model: **assign a responsible person and approver per PR**, reflecting the user's choice on 2026-10-14.
Record review and adoption of this document in [documentation PR #34](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/34).

## Role definitions

| Role | Meaning | Assignment in this repository | Responsibilities |
| --- | --- | --- | --- |
| **R — Responsible** | Performs the work | PR author or person named in the PR or linked issue | Research, implementation, documentation, checks, and records of results and follow-up actions |
| **A — Accountable** | Final responsibility and approval for the activity | **One** CODEOWNER who is distinct from R and the change author | Check scope and results, approve or request changes or reject, and verify open items and completion |
| **C — Consulted** | Consulted before a decision | Relevant feature/distribution owner or another CODEOWNER | Provide input on impact, conditions, and alternatives |
| **I — Informed** | Receives decisions and results | Contributors who use or operate the change | Receive results and applicable changes |

Current CODEOWNERs: `@junhyeok-motech` and `@gihuncho`.
Assign a responsible person and one CODEOWNER approver for each PR.
The existing assignment evidence is [CODEOWNERS](../.github/CODEOWNERS) and
[PR #10](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/10), considered **complete under Git-based record management**.

- Name one A for each activity.
- Assign different people to R and A. If both CODEOWNERs performed the work, appoint an independent reviewer.
- Record `Not applicable` when C or I is not needed.
- Assign a real person as R for activities using Dependabot, CI, Codex, or similar tools.
- A gives final approval for the activity within this repository.

## Responsibility matrix

Record actual accounts for these roles in each PR or linked issue.
`Assigned CODEOWNER` means the one person selected as A under the rules above.

| ID | Activity | R — Responsible | A — Accountable | C — Consulted | I — Informed | Completion evidence |
| --- | --- | --- | --- | --- | --- | --- |
| RACI-01 | Review, adopt, or exclude OSS candidates | Owner of the adoption proposal PR | Assigned CODEOWNER | Owner of the feature using the OSS | Affected development and operations owners | Component, version, purpose, review evidence, decision, and approved PR |
| RACI-02 | Review license texts, distribution terms, and individual cases | Owner of the dependency PR | Assigned CODEOWNER | Relevant distribution owner; qualified reviewer if interpretation is needed | Owners using or distributing the OSS | Texts, version, hashes, terms review, and approval review |
| RACI-03 | Change acceptance and selection exclusion policies | Owner of the policy PR | Assigned CODEOWNER | Affected feature owners and CI owner | Repository contributors | Policy documents, code, tests, and approved PR |
| RACI-04 | Update dependencies and locks; verify SBOMs | Owner of the dependency PR; a designated person for bot PRs | Assigned CODEOWNER | Relevant MCP/feature owner | Distribution and operations owners | Lock diff, SBOM, and check results for the same target commit |
| RACI-05 | Assess, fix, and close vulnerabilities | Owner of the remediation PR or issue | Assigned CODEOWNER | Affected feature/distribution owners | Affected users and operations owners | Advisory ID, affected version, fix commit, repeat scan, and closure decision |
| RACI-06 | Accept, reassess, or remove vulnerability exceptions | Owner of the exception PR | Assigned CODEOWNER | Affected feature/distribution owners; security reviewer as needed | Development and operations owners applying the exception | Acceptance reason, reassessment conditions, exception-list diff, and approved PR |
| RACI-07 | Verify distribution notices and bundled licenses | Owner of the distribution | Assigned CODEOWNER | Owners of dependency and notice changes | Distribution and operations owners | Verification of NOTICE/LICENSE and third-party notices in the actual distribution |
| RACI-08 | Review weekly automated checks | Person named in the check issue or record PR | Assigned CODEOWNER | Feature owners for failing items | Remediation and relevant operations owners | Scheduled run, human review, findings, and follow-up PRs |
| RACI-09 | Preserve CI evidence before expiration | Owner of the preservation issue or record PR | Assigned CODEOWNER | Relevant release/check owner | Evidence reviewers and relevant contributors | Target commit, run, hashes, storage location, and copy verification record |
| RACI-10 | Change ownership and hand over work | Owner of the handover record PR | Assigned CODEOWNER | Outgoing and incoming owners | Contributors involved in the activity | Responsibility changes and confirmed handover of open items, deadlines, and evidence locations |

## Procedure

1. **Start**: Define scope and record R and A accounts in the PR or linked issue. Record C for required consultation and I for recipients of results.
2. **Perform**: R links the evidence required by the matrix. Keep C's input and its disposition in the same PR or issue.
3. **Review**: A checks evidence and remaining actions, then approves or requests changes. Record approval of PR changes through a GitHub review.
4. **Complete**: For changes, verify approval, required checks, and merge. For operational checks, verify review of results and the completion decision. Link remaining actions to separate issues/PRs and owners.
5. **Share and retain**: Link results where I can access them. Preserve needed CI artifacts before expiration; use Git/PRs as the originals for documents, approvals, and remediation history.
6. **Hand over**: Record the successor and handover details in the same PR or issue.

Record owners and review results for scheduled checks and evidence preservation in an issue or documentation PR.

## Minimum PR or issue record

Reuse existing PR records when authors, approvers, and validation results are clear.
Add the following fields when further assignment is needed.

```text
Activity / scope: RACI-__ / target OSS and version, or operational check scope
R: @actual-responsible-person
A: @one-CODEOWNER-distinct-from-the-author
C: @consulted-person or Not applicable
I: result recipients or Not applicable
Evidence: links to documents, commits, check runs, and artifacts
Decision: In progress / Changes needed / Complete (link actual approval/review)
Follow-up: action, owner, and deadline, or Not applicable
```

## Example supported by existing records

[PR #24](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/24) provides the following GitHub records.

| Item | Actual record |
| --- | --- |
| Activity | SBOM generation, license checks, and PDF wheel review |
| Author / evidence for R | `@gihuncho`, PR authorship and change commits |
| Approver / evidence for A | `@junhyeok-motech`, approval review at 2026-10-07 01:45:43 UTC |
| Reviewed commit | `d80e06599fbedef6cb5e9359d256a53c1c783307` |
| Applied | Merged at 2026-10-07 01:46:16 UTC |
| Evidence | Changed files, validation results, and linked Security runs in the PR |

Authorship, approval, and application history for this example are **complete under Git-based record management**.

## Document review results

Checked: 2026-10-16 · Content cross-check: Codex.
The document's rules, responsibility matrix, and evidence were checked.

- [x] Reflects the user's choice of per-PR responsible persons and approvers.
- [x] Matches the two CODEOWNERS accounts and specifies one A, distinct from R and the change author.
- [x] Requires a real person to own bot PRs and scheduled checks.
- [x] Defines C/I assignment and how to record `Not applicable`.
- [x] Covers R/A/C/I and completion evidence for ten activities, plus follow-up, retention, and handover criteria.
- [x] Compared PR #24's author, approver, reviewed commit, approval time, and merge time with actual GitHub records.

## Checks for each activity

Record the results of these checks in the corresponding PR or issue.

| Check | Evidence in the PR or issue |
| --- | --- |
| Responsible person and approver | Actual R and A accounts, one A, distinct from R and the change author |
| Automated work | The real person responsible for bot PRs or scheduled check results |
| Consultation and sharing | Required C/I accounts or explicit `Not applicable` |
| Completion | Evidence for the activity and actual approval/review records |
| Remaining actions | Owners, deadlines, and follow-up links for open actions |
| Long-term evidence retention | Owner, storage location, and completed-copy record when separate preservation is needed |
