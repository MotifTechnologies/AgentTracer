"""Shared streaming reader for object-valued JSONL datasets."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_tracer.config.schema import ConfigError


def iter_jsonl_rows(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield physical line numbers and objects, with contextual input errors."""
    if not path.is_file():
        raise ConfigError(f"dataset: {path} not found")
    with path.open(encoding="utf-8") as source:
        for lineno, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    f"dataset: {path}:{lineno} invalid JSON: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise ConfigError(f"dataset: {path}:{lineno} must be a JSON object")
            yield lineno, row
