"""Additional training-format exporters on top of the ShareGPT records.

- HuggingFace Dataset: the ShareGPT records materialized as an Arrow dataset
  (``datasets.Dataset``), saved with ``save_to_disk`` — loadable via
  ``datasets.load_from_disk`` and pushable to the Hub as-is.
- GRPO JSONL: one line per sample with ``prompt`` / ``completion`` message
  lists, a scalar ``reward``, and a ``group_id`` (the task id) so trainers can
  group multiple samples of the same task for relative advantage estimation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def records_to_hf_dataset(records: list[dict[str, Any]], output_dir: Path) -> int:
    from datasets import Dataset

    dataset = Dataset.from_list(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset.save_to_disk(str(output_dir))
    return len(dataset)


def record_to_grpo_row(record: dict[str, Any]) -> dict[str, Any]:
    """Split a ShareGPT record into prompt/completion and attach a reward.

    Prompt = everything before the first assistant turn (system + task).
    Completion = the agent's full interaction (assistant + tool turns).
    Reward = evaluation score when present, else 1.0/0.0 from correctness,
    else None (unevaluated samples still export; trainers may filter).
    """
    conversations = record["conversations"]
    first_assistant = next(
        (i for i, m in enumerate(conversations) if m["role"] == "assistant"),
        len(conversations),
    )
    evaluation = record["extra"].get("evaluation") or {}
    reward = evaluation.get("score")
    if reward is None and evaluation.get("correct") is not None:
        reward = 1.0 if evaluation["correct"] else 0.0

    return {
        "group_id": record["extra"]["task"],
        "prompt": conversations[:first_assistant],
        "completion": conversations[first_assistant:],
        "reward": reward,
        "correct": evaluation.get("correct"),
        "exit_status": record["extra"].get("exit_status"),
        "model": record["source"]["synthetic"].get("model"),
        "tools": record["tools"],
    }


def records_to_grpo_jsonl(records: list[dict[str, Any]], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record_to_grpo_row(record), ensure_ascii=False) + "\n")
    return len(records)
