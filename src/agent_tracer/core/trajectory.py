"""Trajectory: the structured event-stream record of one task run.

Format ``agent-tracer-1.0``: an envelope of per-event dicts plus run metadata.
Events are appended in wall-clock order by the recorder; the file is written
once, atomically, when the task finishes (checkpoint-friendly).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAJECTORY_FORMAT = "agent-tracer-1.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    event_id: str
    event_type: str
    agent_id: str | None
    timestamp: str
    data: dict[str, Any]


@dataclass
class TokenTotals:
    input: int = 0
    reasoning: int = 0
    answer: int = 0

    def add(self, input_: int, reasoning: int, answer: int) -> None:
        self.input += input_
        self.reasoning += reasoning
        self.answer += answer


@dataclass
class Trajectory:
    task_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    timestamp_start: str = field(default_factory=utcnow)
    timestamp_end: str | None = None
    token_totals: TokenTotals = field(default_factory=TokenTotals)

    def add_event(self, event_type: str, data: dict[str, Any], agent_id: str | None = None) -> Event:
        event = Event(
            event_id=f"e{len(self.events) + 1:04d}",
            event_type=event_type,
            agent_id=agent_id,
            timestamp=utcnow(),
            data=data,
        )
        self.events.append(event)
        return event

    def finish(self, result: dict[str, Any]) -> None:
        self.result = result
        self.timestamp_end = utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_format": TRAJECTORY_FORMAT,
            "task_id": self.task_id,
            "metadata": {
                **self.metadata,
                "timestamp_start": self.timestamp_start,
                "timestamp_end": self.timestamp_end,
                "total_tokens": asdict(self.token_totals),
            },
            "events": [asdict(e) for e in self.events],
            "result": self.result,
        }

    def save(self, directory: Path) -> Path:
        """Atomically write ``<task_id>.traj.json`` (temp file + rename)."""
        directory.mkdir(parents=True, exist_ok=True)
        safe_id = self.task_id.replace(os.sep, "_")
        path = directory / f"{safe_id}.traj.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.rename(path)
        return path
