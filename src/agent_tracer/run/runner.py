"""Async batch runner: semaphore-bounded concurrency, checkpoint resume,
and a single compact progress display (bar / done-total / TPS / ETA).

All per-agent console output is silenced (TrajectoryRecorder is a no-print
logger); this progress line is the only thing the runner shows.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

from agent_tracer.config.schema import RunConfig
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.datasets.custom import get_dataset
from agent_tracer.mcp.discovery import build_stirrup_mcp_config, discover_mcp_servers
from agent_tracer.orchestrators.single import SingleAgentOrchestrator


class _TPSColumn(ProgressColumn):
    """Output tokens per second, aggregated across all concurrent tasks."""

    def __init__(self, counter: "_TokenCounter") -> None:
        super().__init__()
        self._counter = counter

    def render(self, task) -> Text:
        return Text(f"{self._counter.tps():,.0f} tok/s", style="cyan")


class _TokenCounter:
    def __init__(self) -> None:
        self.output_tokens = 0
        self.started = time.monotonic()

    def on_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.output_tokens += output_tokens

    def tps(self) -> float:
        elapsed = time.monotonic() - self.started
        return self.output_tokens / elapsed if elapsed > 0 else 0.0


class Runner:
    def __init__(self, config: RunConfig):
        self.config = config
        self.manifests = discover_mcp_servers(config.mcp)
        self.mcp_config = (
            build_stirrup_mcp_config(self.manifests, config.mcp.resolved_discovery_dir())
            if self.manifests
            else None
        )
        self.orchestrator = SingleAgentOrchestrator(config, self.mcp_config)
        self.trajectory_dir = config.output.path / "trajectories"
        self.results_path = config.output.path / "results.jsonl"

    def _base_metadata(self) -> dict[str, Any]:
        return {
            "dataset": self.config.dataset.name,
            "orchestrator": "single",
            "model": {
                "model_name": self.config.model.model_name,
                "base_url": self.config.model.base_url,
                "reasoning_key": self.config.model.reasoning_key,
            },
            "environment": self.config.environment.type,
            "mcp_servers": {
                name: {"version": m.version, "transport": m.transport}
                for name, m in self.manifests.items()
            },
            "agent": {
                "role": self.config.agent.role,
                "max_turns": self.config.agent.max_turns,
            },
        }

    def _completed_task_ids(self) -> set[str]:
        if not (self.config.runner.checkpoint and self.results_path.is_file()):
            return set()
        done = set()
        for line in self.results_path.read_text("utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("exit_status") != "error":
                    done.add(row["task_id"])
        return done

    async def _run_one(self, task: Task, counter: _TokenCounter) -> dict[str, Any]:
        retry = self.config.runner.retry
        last_error: str | None = None

        for attempt in range(1, retry.max_attempts + 1):
            trajectory = Trajectory(task_id=task.task_id, metadata=self._base_metadata())
            try:
                result = await asyncio.wait_for(
                    self.orchestrator.run_task(task, trajectory, on_tokens=counter.on_tokens),
                    timeout=self.config.runner.task_timeout,
                )
                dataset = get_dataset(self.config.dataset.name, self.config.dataset.path)
                evaluation = dataset.evaluate(task, result["submission"])
                trajectory.finish(
                    {
                        "submission": result["submission"],
                        "exit_status": result["exit_status"],
                        "evaluation": asdict(evaluation),
                        "attempt": attempt,
                    }
                )
                if self.config.output.save_trajectories:
                    trajectory.save(self.trajectory_dir)
                return {
                    "task_id": task.task_id,
                    "exit_status": result["exit_status"],
                    "submission": result["submission"],
                    "correct": evaluation.correct,
                    "tokens": asdict(trajectory.token_totals),
                    "attempt": attempt,
                }
            except (TimeoutError, asyncio.TimeoutError):
                last_error = f"task timeout after {self.config.runner.task_timeout}s"
            except Exception as e:  # noqa: BLE001 — record and retry per policy
                last_error = f"{type(e).__name__}: {e}"

            trajectory.add_event("error", {"message": last_error, "attempt": attempt})
            if attempt < retry.max_attempts:
                await asyncio.sleep(retry.backoff_base**attempt)

        trajectory.finish({"submission": None, "exit_status": "error", "error": last_error})
        if self.config.output.save_trajectories:
            trajectory.save(self.trajectory_dir)
        return {
            "task_id": task.task_id,
            "exit_status": "error",
            "submission": None,
            "correct": None,
            "error": last_error,
            "attempt": retry.max_attempts,
        }

    async def run(self) -> list[dict[str, Any]]:
        dataset = get_dataset(self.config.dataset.name, self.config.dataset.path)
        tasks = dataset.load(self.config.dataset.split, self.config.dataset.limit)

        done_ids = self._completed_task_ids()
        pending = [t for t in tasks if t.task_id not in done_ids]

        self.config.output.path.mkdir(parents=True, exist_ok=True)
        counter = _TokenCounter()
        semaphore = asyncio.Semaphore(self.config.runner.max_concurrency)
        results: list[dict[str, Any]] = []
        results_lock = asyncio.Lock()

        progress = Progress(
            TextColumn("[bold]agent-tracer[/bold]"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            _TPSColumn(counter),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
            transient=False,
        )
        bar = progress.add_task("run", total=len(tasks), completed=len(done_ids))

        async def worker(task: Task) -> None:
            async with semaphore:
                row = await self._run_one(task, counter)
            async with results_lock:
                results.append(row)
                with self.results_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            progress.advance(bar)

        with progress:
            await asyncio.gather(*(worker(t) for t in pending))
        return results
