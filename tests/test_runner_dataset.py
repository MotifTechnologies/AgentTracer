import asyncio
from unittest.mock import AsyncMock, Mock

from agent_tracer.config.schema import RunConfig
from agent_tracer.core.task import Task
from agent_tracer.run import runner as runner_module


def _config(tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text('{"task_id":"t1","input":"question","reference":"42"}\n')
    return RunConfig.model_validate(
        {
            "dataset": {"name": "custom", "path": path},
            "model": {
                "model_name": "test",
                "base_url": "http://example.invalid",
                "api_key": "test-only-key",
                "reasoning_key": "none",
            },
            "mcp": {"include": []},
            "runner": {
                "samples_per_task": 2,
                "checkpoint": False,
                "retry": {"max_attempts": 1},
            },
            "output": {"path": tmp_path / "out", "save_trajectories": False},
        }
    )


def test_run_one_evaluates_without_first_running_a_batch(tmp_path):
    runner = runner_module.Runner(_config(tmp_path))
    run_task = AsyncMock(return_value={"submission": "42", "exit_status": "submitted"})
    runner.orchestrator.run_task = run_task
    task = Task("t1", "question", reference="42")

    result = asyncio.run(runner._run_one(task, 0, runner_module._TokenCounter()))

    assert result["exit_status"] == "submitted"
    assert result["correct"] is True
    run_task.assert_awaited_once()


def test_reused_runner_constructs_one_dataset_and_evaluates_all_samples(
    tmp_path, monkeypatch
):
    factory = Mock(wraps=runner_module.get_dataset)
    monkeypatch.setattr(runner_module, "get_dataset", factory)
    runner = runner_module.Runner(_config(tmp_path))
    runner.orchestrator.run_task = AsyncMock(
        return_value={"submission": "42", "exit_status": "submitted"}
    )

    for _ in range(2):
        rows = asyncio.run(runner.run())
        assert len(rows) == 2
        assert all(row["correct"] is True for row in rows)
    factory.assert_called_once()
