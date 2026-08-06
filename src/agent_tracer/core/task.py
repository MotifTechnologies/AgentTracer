from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    task_id: str
    input: str
    metadata: dict[str, Any] = field(default_factory=dict)
    reference: str | None = None
    attachments: dict[str, Any] | None = None


@dataclass
class EvalResult:
    correct: bool | None
    score: float | None = None
    details: dict[str, Any] | None = None
