"""CustomDataset: JSONL loader — one task per line.

Line schema: {"task_id": str, "input": str, "reference"?: str, "metadata"?: dict}
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tracer.config.schema import ConfigError
from agent_tracer.core.task import EvalResult, Task


class CustomDataset:
    name = "custom"

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
            if "task_id" not in row or "input" not in row:
                raise ConfigError(f"dataset: {self.path}:{lineno} requires task_id and input")
            tasks.append(
                Task(
                    task_id=str(row["task_id"]),
                    input=row["input"],
                    metadata=row.get("metadata", {}),
                    reference=row.get("reference"),
                    attachments=row.get("attachments"),
                )
            )
            if limit is not None and len(tasks) >= limit:
                break
        return tasks

    def evaluate(self, task: Task, submission: str | None) -> EvalResult:
        if task.reference is None or submission is None:
            return EvalResult(correct=None)
        correct = submission.strip() == task.reference.strip()
        return EvalResult(correct=correct, score=1.0 if correct else 0.0)


def get_dataset(name: str, path: Path | None):
    if name == "custom":
        return CustomDataset(path)  # path validated in config schema
    if name == "swebench_local":
        from agent_tracer.datasets.swebench_local import SWEBenchLocalDataset

        return SWEBenchLocalDataset(path)
    raise ConfigError(f"dataset: unknown dataset {name!r} (supported: custom, swebench_local)")
