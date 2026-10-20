"""Async batch runner: semaphore-bounded concurrency, checkpoint resume,
and a single compact progress display (bar / done-total / TPS / ETA).

All per-agent console output is silenced (TrajectoryRecorder is a no-print
logger); this progress line is the only thing the runner shows.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from dataclasses import asdict
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
from agent_tracer.datasets.bfcl_fixture import BFCLFixtureDataset
from agent_tracer.datasets.custom import get_dataset
from agent_tracer.environments import SandboxMissingBinariesError
from agent_tracer.mcp.discovery import build_stirrup_mcp_config, discover_mcp_servers
from agent_tracer.orchestrators.single import SingleAgentOrchestrator


class _TPSColumn(ProgressColumn):
    """Output tokens per second, aggregated across all concurrent tasks."""

    def __init__(self, counter: _TokenCounter) -> None:
        super().__init__()
        self._counter = counter

    def render(self, task) -> Text:
        return Text(f"{self._counter.tps():,.0f} tok/s", style="cyan")


def describe_exception(exc: BaseException, *, depth: int = 0) -> str:
    """A message that names the actual failure.

    ``str()`` on an ExceptionGroup is only "unhandled errors in a TaskGroup
    (1 sub-exception)" — the cause is in ``exceptions``. stirrup runs its tools
    in a TaskGroup, so every tool-side failure arrived wearing that wrapper and
    the results file recorded nothing usable about it.
    """
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions and depth < 4:
        inner = ", ".join(
            describe_exception(sub, depth=depth + 1) for sub in exc.exceptions[:3]
        )
        return f"{type(exc).__name__}[{inner}]"
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


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
        self.manifests = (
            {}
            if config.dataset.name == "bfcl_fixture"
            else discover_mcp_servers(config.mcp)
        )
        self.mcp_config = (
            build_stirrup_mcp_config(
                self.manifests, config.mcp.resolved_discovery_dir()
            )
            if self.manifests
            else None
        )
        self.orchestrator: Any = SingleAgentOrchestrator(
            config,
            self.mcp_config,
            manifests=self.manifests or None,
            mcp_root=config.mcp.resolved_discovery_dir() if self.manifests else None,
        )
        if config.dataset.name == "bfcl_fixture":
            from agent_tracer.orchestrators.bfcl_fixture import BFCLFixtureOrchestrator

            self.orchestrator = BFCLFixtureOrchestrator(config)
        self.trajectory_dir = config.output.path / "trajectories"
        self.results_path = config.output.path / "results.jsonl"
        self.fixture_run_digest: str | None = None
        if config.dataset.name == "bfcl_fixture":
            self._validate_fixture_output()

    def _validate_fixture_output(self) -> None:
        config = self.config
        from agent_tracer.config.schema import ConfigError
        from agent_tracer.datasets.bfcl_fixture import digest

        if config.runner.retry.max_attempts != 1 or config.model.max_retries != 0:
            raise ConfigError(
                "bfcl_fixture disallows automatic API/task retries; inspect journals and explicitly recover uncertain requests"
            )
        data_path = config.dataset.path
        assert data_path is not None
        manifest = {
            "dataset_sha256": __import__("hashlib")
            .sha256(data_path.read_bytes())
            .hexdigest(),
            "model_config_sha256": digest(config.model.model_dump(exclude={"api_key"})),
            "agent": config.agent.model_dump(),
            "runner": config.runner.model_dump(),
            "protocol": "native-fc-no-tool-turn-end-v1",
        }
        self.fixture_run_digest = digest(manifest)
        manifest["binding_sha256"] = self.fixture_run_digest
        config.output.path.mkdir(parents=True, exist_ok=True)
        path = config.output.path / "fixture-run-manifest.json"
        if path.exists():
            if json.loads(path.read_text("utf-8")) != manifest:
                raise ConfigError(
                    "fixture/config changed under an existing output; use a new output directory"
                )
        else:
            # A missing binding must not adopt another run's results or journals.
            # The reservation is the only entry created by this collector itself.
            if any(
                entry.name != ".fixture-collector.lock"
                for entry in config.output.path.iterdir()
            ):
                raise ConfigError(
                    "existing output without a fixture manifest cannot be verified; use a new output directory"
                )
            with path.open("x", encoding="utf-8") as out:
                json.dump(manifest, out, indent=2)
        for journal in (config.output.path / "requests").glob("*.jsonl"):
            pending = set()
            with journal.open(encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    if row.get("run_manifest_sha256") != self.fixture_run_digest:
                        raise ConfigError(
                            "request journal binding differs; inspect before resume"
                        )
                    identity = (row.get("attempt"), row["step"])
                    if row["kind"] == "request":
                        if identity in pending:
                            raise ConfigError("duplicate unresolved API request")
                        pending.add(identity)
                    else:
                        pending.discard(identity)
            if pending:
                raise ConfigError(
                    "unresolved API request; do not blindly resume/retry; inspect remote provider and journal"
                )
            stem = journal.name.removesuffix(".jsonl")
            task_id, sample_text = stem.rsplit(".s", 1)
            if (task_id, int(sample_text)) not in self._completed_samples():
                raise ConfigError(
                    "existing API journal without terminal sample result; recover saved responses offline, never repeat paid calls blindly"
                )

    def _base_metadata(self) -> dict[str, Any]:
        return {
            "dataset": self.config.dataset.name,
            "orchestrator": "bfcl_fixture"
            if self.config.dataset.name == "bfcl_fixture"
            else "single",
            "model": {
                "model_name": self.config.model.model_name,
                "base_url": self.config.model.base_url,
                "reasoning_key": self.config.model.reasoning_key,
                "reasoning_effort": self.config.model.reasoning_effort,
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

    def _completed_samples(self) -> set[tuple[str, int]]:
        """Which (task, sample) pairs already succeeded — keyed on both, so a
        resumed run does not mistake sample 0 for the whole task."""
        if not (self.config.runner.checkpoint and self.results_path.is_file()):
            return set()
        done = set()
        with self.results_path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    row = json.loads(line)
                    if row.get("exit_status") != "error":
                        done.add((row["task_id"], row.get("sample_idx", 0)))
        return done

    async def _run_one(
        self, task: Task, sample_idx: int, counter: _TokenCounter
    ) -> dict[str, Any]:
        retry = self.config.runner.retry
        last_error: str | None = None

        for attempt in range(1, retry.max_attempts + 1):
            trajectory = Trajectory(
                task_id=task.task_id,
                sample_idx=sample_idx,
                metadata={
                    **self._base_metadata(),
                    "run_manifest_sha256": self.fixture_run_digest,
                    "attempt": attempt,
                },
            )
            try:
                result = await asyncio.wait_for(
                    self.orchestrator.run_task(
                        task, trajectory, on_tokens=counter.on_tokens
                    ),
                    timeout=self.config.runner.task_timeout,
                )
                dataset = get_dataset(
                    self.config.dataset.name, self.config.dataset.path
                )
                if isinstance(dataset, BFCLFixtureDataset):
                    evaluation = dataset.evaluate_trajectory(task, trajectory)
                else:
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
                    "sample_idx": sample_idx,
                    "exit_status": result["exit_status"],
                    "submission": result["submission"],
                    "correct": evaluation.correct,
                    "tokens": asdict(trajectory.token_totals),
                    "attempt": attempt,
                }
            except TimeoutError:
                last_error = f"task timeout after {self.config.runner.task_timeout}s"
            except SandboxMissingBinariesError as e:
                # Not transient: the image will not grow the binary between
                # attempts. The shared config image dooms every task, so the
                # run aborts; an image the task shipped breaks only this task.
                if e.run_fatal:
                    raise
                last_error = describe_exception(e)
                trajectory.add_event(
                    "error", {"message": last_error, "attempt": attempt}
                )
                break
            except Exception as e:
                last_error = describe_exception(e)

            trajectory.add_event("error", {"message": last_error, "attempt": attempt})
            if attempt < retry.max_attempts:
                await asyncio.sleep(retry.backoff_base**attempt)

        trajectory.finish(
            {"submission": None, "exit_status": "error", "error": last_error}
        )
        if self.config.output.save_trajectories:
            trajectory.save(self.trajectory_dir)
        return {
            "task_id": task.task_id,
            "sample_idx": sample_idx,
            "exit_status": "error",
            "submission": None,
            "correct": None,
            "error": last_error,
            "attempt": retry.max_attempts,
        }

    @staticmethod
    def _task_image(task: Task) -> str | None:
        """The image this task brought, if any. Config images are not released."""
        return (task.metadata or {}).get("docker_image")

    async def _release_when_last(
        self, task: Task, remaining: Counter, lock: asyncio.Lock
    ) -> None:
        """Drop a task's image once its final rollout is done.

        Counted rather than dropped eagerly: with samples_per_task > 1 the
        siblings share the image, and removing it after the first would make
        every other sample pull it again. Runs after the rollout returns, so
        the container is already torn down.
        """
        image = self._task_image(task)
        if not image or not self.config.environment.release_task_images:
            return
        async with lock:
            remaining[image] -= 1
            if remaining[image] > 0:
                return
        from agent_tracer.environments import release_image

        await asyncio.to_thread(release_image, self.config.environment.type, image)

    async def run(self) -> list[dict[str, Any]]:
        if self.config.dataset.name == "bfcl_fixture":
            from agent_tracer.run.fixture_lock import exclusive_fixture_output

            with exclusive_fixture_output(self.config.output.path):
                # Recheck under the lock: this Runner may have been constructed
                # before another collector changed the output.
                self._validate_fixture_output()
                return await self._run_batch()
        return await self._run_batch()

    async def _run_batch(self) -> list[dict[str, Any]]:
        dataset = get_dataset(self.config.dataset.name, self.config.dataset.path)
        tasks = dataset.load(self.config.dataset.split, self.config.dataset.limit)

        samples = self.config.runner.samples_per_task
        done = self._completed_samples()
        wanted = [(t, i) for t in tasks for i in range(samples)]
        pending = [(t, i) for t, i in wanted if (t.task_id, i) not in done]

        self.config.output.path.mkdir(parents=True, exist_ok=True)
        counter = _TokenCounter()
        semaphore = asyncio.Semaphore(self.config.runner.max_concurrency)
        results: list[dict[str, Any]] = []
        results_lock = asyncio.Lock()
        remaining_by_image: Counter = Counter(
            image for task, _ in pending if (image := self._task_image(task))
        )
        image_lock = asyncio.Lock()

        progress = Progress(
            TextColumn("[bold]agent-tracer[/bold]"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            _TPSColumn(counter),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
            transient=False,
            # rich estimates speed from the last 30 seconds by default. A task
            # that takes minutes never advances inside that window, so the
            # estimate is always empty and the ETA reads -:--:-- for the whole
            # run. An hour of history covers the slowest task here.
            speed_estimate_period=3600,
        )
        bar = progress.add_task(
            "run", total=len(wanted), completed=len(wanted) - len(pending)
        )

        async def worker(task: Task, sample_idx: int) -> None:
            async with semaphore:
                row = await self._run_one(task, sample_idx, counter)
            async with results_lock:
                results.append(row)
                with self.results_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            progress.advance(bar)
            await self._release_when_last(task, remaining_by_image, image_lock)

        with progress:
            workers = [asyncio.create_task(worker(t, i)) for t, i in pending]
            try:
                await asyncio.gather(*workers)
            except BaseException:
                # Do not release a fixture reservation while sibling requests
                # still run. Their journals remain available for recovery.
                for running in workers:
                    running.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                raise
        return results
