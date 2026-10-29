# Governance

AgentTracer is maintained by Motif Technologies. This page says who is
responsible for what and how decisions are made. The current maintainers are
the owners listed in [`.github/CODEOWNERS`](.github/CODEOWNERS).

## Roles

| Role | Responsibilities |
| --- | --- |
| Project lead | Release direction, license review, final decision on RFCs |
| Community lead | Answering Discussions, writing release notes, running beta tests |
| Technical reviewer | Reviewing external pull requests, checking integration tests, finding good first issues |
| Docs and outreach | Technical blog posts, Hugging Face content |

One person may hold more than one role.

## How decisions are made

| Change | Process |
| --- | --- |
| Bug fix or small feature | A pull request merges after one reviewer approves it and the required checks pass. The `main` branch rules enforce both. |
| Major feature or architecture change | Post an RFC in [Discussions Ideas](https://github.com/MotifTechnologies/AgentTracer/discussions/categories/ideas). It stays open for feedback for 7 days. The project lead then decides and records the outcome in the discussion. The pull request links to it. |
| Security vulnerability | Report privately as described in [SECURITY.md](SECURITY.md). First response within 3 working days. A fix is released before the issue is made public. |

For response targets on issues and questions, see
[CONTRIBUTING.md](CONTRIBUTING.md#response-targets).

## Releases

Releases are tagged and published on GitHub. Release notes are generated from
pull request labels, grouped as set in [`.github/release.yml`](.github/release.yml).
