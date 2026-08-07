"""Tier-1 patch grading: cheap similarity between a submitted and a gold diff.

Ported from the v1 agenttracer offline grading design
(docs/train-trajectory-grading.md): for crawled SWE-style instances there is
no FAIL_TO_PASS test list, only a gold ``patch``. Tier 1 triages trajectories
by structural similarity; borderline cases can be escalated to an LLM judge
(tier 2) or derived-test execution (tier 3) offline.

Signals:
- ``files_match``: |touched(submission) ∩ touched(gold)| / |touched(gold)|
- ``added_sim`` / ``removed_sim``: SequenceMatcher ratio over the joined
  added / removed lines (headers excluded, stripped).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_DIFF_HEADER = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)", re.MULTILINE)


def touched_files(patch: str) -> set[str]:
    return {m.group("b") for m in _DIFF_HEADER.finditer(patch or "")}


def _changed_lines(patch: str, sign: str) -> str:
    lines = []
    for line in (patch or "").splitlines():
        if line.startswith(sign) and not line.startswith(sign * 3):
            lines.append(line[1:].strip())
    return "\n".join(lines)


@dataclass
class PatchSimilarity:
    files_match: float
    added_sim: float
    removed_sim: float

    @property
    def score(self) -> float:
        """Single triage score in [0, 1]: file overlap gated, content-weighted."""
        return self.files_match * (0.7 * self.added_sim + 0.3 * self.removed_sim)


def compare_patches(submission: str, gold: str) -> PatchSimilarity:
    gold_files = touched_files(gold)
    sub_files = touched_files(submission)
    files_match = len(sub_files & gold_files) / len(gold_files) if gold_files else 0.0

    added_sim = SequenceMatcher(
        None, _changed_lines(submission, "+"), _changed_lines(gold, "+")
    ).ratio()
    removed_sim = SequenceMatcher(
        None, _changed_lines(submission, "-"), _changed_lines(gold, "-")
    ).ratio()
    return PatchSimilarity(files_match=files_match, added_sim=added_sim, removed_sim=removed_sim)
