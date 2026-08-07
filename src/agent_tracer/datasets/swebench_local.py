"""Loader for locally-crawled SWE-style instances (NOT the SWE-bench benchmark).

Seed strategy for the coding/bash domain without benchmark contamination:
instances are crawled from public GitHub repos (issue text + gold patch) in a
SWE-bench-shaped JSONL. Ported from v1 agenttracer's ``swebench_local``.

Expected keys per line: ``repo``, ``instance_id``, ``base_commit``,
``problem_statement``, ``patch`` (gold reference, recorded not graded),
optional ``test_patch`` / ``hints_text`` / ``created_at``.

Correctness grading is deliberately absent: task-specific verifiers (test
execution, state assertions, answer matching) belong to benchmark harnesses,
not to this framework, whose job is to run agents and record trajectories.
The gold patch is carried through as ``reference`` so downstream tooling can
grade offline without re-running the agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tracer.config.schema import ConfigError
from agent_tracer.core.task import EvalResult, Task

_REQUIRED = ("repo", "instance_id", "base_commit", "problem_statement", "patch")

_TASK_INSTRUCTIONS = (
    "You are working in a checkout of the repository {repo} at commit {base_commit}.\n"
    "Resolve the following issue. When done, submit the fix as a unified git diff "
    "(the full `git diff` output) via the submit tool.\n\n"
    "## Issue\n{problem_statement}"
)


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
        """No correctness verdict: patch equivalence needs a test harness.

        Returns ``correct=None`` so records stay honest about being ungraded;
        dataset-level quality gating (well-formedness, completeness) happens on
        the exported records instead.
        """
        return EvalResult(correct=None, details={"graded": False})
