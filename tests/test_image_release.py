import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest

from agent_tracer.config.schema import (
    DatasetConfig,
    EnvironmentConfig,
    ModelConfig,
    OutputConfig,
    RunConfig,
)
from agent_tracer.core.task import Task
from agent_tracer.run.runner import Runner


def _runner(tmp_path: Path, **env) -> Runner:
    tasks = tmp_path / "t.jsonl"
    tasks.write_text('{"task_id": "t1", "input": "x"}\n')
    config = RunConfig(
        dataset=DatasetConfig(name="custom", path=tasks),
        model=ModelConfig(model_name="m", base_url="http://x/v1", api_key="k", reasoning_key="none"),
        environment=EnvironmentConfig(type="docker", image="base:1", **env),
        output=OutputConfig(path=tmp_path / "out"),
    )
    return Runner(config)


def _task(image=None):
    return Task(task_id="t", input="x", metadata={"docker_image": image} if image else {})


class TestWhichImagesGetReleased:
    def test_only_images_the_task_brought(self, tmp_path):
        runner = _runner(tmp_path)
        assert runner._task_image(_task("img:task")) == "img:task"
        assert runner._task_image(_task()) is None


class TestReleaseTiming:
    def _run(self, runner, task, remaining, released):
        async def go():
            import agent_tracer.environments as environments

            calls = []
            original = environments.release_image
            environments.release_image = lambda env_type, image: calls.append(image) or True
            try:
                await runner._release_when_last(task, remaining, asyncio.Lock())
            finally:
                environments.release_image = original
            released.extend(calls)

        asyncio.run(go())

    def test_held_until_the_last_sibling_finishes(self, tmp_path):
        runner = _runner(tmp_path)
        task = _task("img:task")
        remaining = Counter({"img:task": 3})
        released: list[str] = []

        for _ in range(2):
            self._run(runner, task, remaining, released)
        assert released == [], "released while siblings still needed it"

        self._run(runner, task, remaining, released)
        assert released == ["img:task"]

    def test_config_image_is_never_released(self, tmp_path):
        runner = _runner(tmp_path)
        released: list[str] = []
        self._run(runner, _task(), Counter(), released)
        assert released == []

    def test_disabled_by_config(self, tmp_path):
        runner = _runner(tmp_path, release_task_images=False)
        released: list[str] = []
        self._run(runner, _task("img:task"), Counter({"img:task": 1}), released)
        assert released == []


class TestReleaseNeverFailsARun:
    def test_a_backend_without_the_hook_is_not_an_error(self):
        from agent_tracer.environments import release_image

        assert release_image("local", "img:task") is False

    def test_a_raising_hook_is_swallowed(self, monkeypatch):
        import agent_tracer.environments as environments

        class Boom:
            def release_image(self, image):
                raise RuntimeError("daemon unreachable")

        monkeypatch.setattr(environments, "_load", lambda env_type: Boom())
        assert environments.release_image("docker", "img:task") is False
