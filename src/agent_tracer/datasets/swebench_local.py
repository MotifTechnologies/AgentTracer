"""Loader for locally-crawled SWE-style instances (NOT the SWE-bench benchmark).

Seed strategy for the coding/bash domain without benchmark contamination:
instances are crawled from public GitHub repos (issue text + gold patch) in a
SWE-bench-shaped JSONL. Ported from v1 agenttracer's ``swebench_local``.

Expected keys per line: ``repo``, ``instance_id``, ``base_commit``,
``problem_statement``, ``patch`` (gold, grading only), optional
``test_patch`` / ``hints_text`` / ``created_at``.

Grading here is tier-1 patch similarity (see ``agent_tracer.eval``); the
returned details carry the raw signals so offline tier-2/3 passes can
re-grade without re-running the agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tracer.config.schema import ConfigError
from agent_tracer.core.task import EvalResult, Task
from agent_tracer.eval.patch_similarity import compare_patches

_REQUIRED = ("repo", "instance_id", "base_commit", "problem_statement", "patch")

_TASK_INSTRUCTIONS = (
    "You are working in a checkout of the repository {repo} at commit {base_commit}.\n"
    "Resolve the following issue. When done, submit the fix as a unified git diff "
    "(the full `git diff` output) via the submit tool.\n\n"
    "## Issue\n{problem_statement}"
)

# Tier-1 triage threshold from v1 field measurements: identical or
# near-identical patches score >= 0.9; genuinely different approaches < 0.2.
# Between the two, correctness is unknown at tier 1 (escalate offline).
CORRECT_THRESHOLD = 0.9
INCORRECT_THRESHOLD = 0.2


class SWEBenchLocalDataset:
    name = "swebench_local"

    def __init__(self, path: Path):
        self.path = path

    def load(self, split: str = "test", limit: int | None = None) -> list[Task]:
        if not self.path.is_file():
            raise ConfigError(f"dataset: {self.path} not found")
        tasks: list[Task] = []
        for lineno, line in enumerate(self.path.read_text("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ConfigError(f"dataset: {self.path}:{lineno} invalid JSON: {e}") from e
            missing = [k for k in _REQUIRED if not row.get(k)]
            if missing:
                raise ConfigError(f"dataset: {self.path}:{lineno} missing keys: {missing}")
            tasks.append(
                Task(
                    task_id=row["instance_id"],
                    input=_TASK_INSTRUCTIONS.format(
                        repo=row["repo"],
                        base_commit=row["base_commit"],
                        problem_statement=row["problem_statement"],
                    ),
                    metadata={
                        "repo": row["repo"],
                        "base_commit": row["base_commit"],
                        "hints_text": row.get("hints_text"),
                        "created_at": row.get("created_at"),
                        "test_patch": row.get("test_patch"),
                    },
                    reference=row["patch"],
                )
            )
            if limit is not None and len(tasks) >= limit:
                break
        return tasks

    def evaluate(self, task: Task, submission: str | None) -> EvalResult:
        if submission is None:
            return EvalResult(correct=None)
        similarity = compare_patches(submission, task.reference or "")
        score = similarity.score
        if score >= CORRECT_THRESHOLD:
            correct: bool | None = True
        elif score < INCORRECT_THRESHOLD:
            correct = False
        else:
            correct = None  # tier-1 cannot decide; escalate to tier 2/3 offline
        return EvalResult(
            correct=correct,
            score=round(score, 4),
            details={
                "tier": 1,
                "files_match": round(similarity.files_match, 4),
                "added_sim": round(similarity.added_sim, 4),
                "removed_sim": round(similarity.removed_sim, 4),
            },
        )
