import json
from pathlib import Path

import pytest

from agent_tracer.config.schema import ConfigError, EnvironmentConfig
from agent_tracer.core.task import Task
from agent_tracer.datasets.swebench_local import SWEBenchLocalDataset

PATCH = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"


def _seed(tmp_path: Path, **extra) -> Path:
    row = {
        "repo": "org/repo",
        "instance_id": "org__repo-1",
        "base_commit": "abc",
        "problem_statement": "fix it",
        "patch": PATCH,
    }
    row.update(extra)
    path = tmp_path / "seeds.jsonl"
    path.write_text(json.dumps(row) + "\n")
    return path


class TestLoaderCarriesRunRequirements:
    def test_image_and_provenance_reach_metadata(self, tmp_path):
        path = _seed(
            tmp_path,
            docker_image="docker.io/x/y:1",
            language="go",
            license_name="MIT",
            fail_to_pass=["TestFoo"],
        )
        task = SWEBenchLocalDataset(path).load()[0]
        assert task.metadata["docker_image"] == "docker.io/x/y:1"
        assert task.metadata["language"] == "go"
        assert task.metadata["license_name"] == "MIT"
        assert task.metadata["fail_to_pass"] == ["TestFoo"]

    def test_absent_image_is_none_not_missing(self, tmp_path):
        task = SWEBenchLocalDataset(_seed(tmp_path)).load()[0]
        assert task.metadata["docker_image"] is None


class TestPerTaskImageSelection:
    def _env_for(self, task: Task, env: EnvironmentConfig) -> EnvironmentConfig:
        """Mirror the orchestrator's per-task environment derivation."""
        from agent_tracer.orchestrators.single import SingleAgentOrchestrator

        update = {"working_dir": env.task_working_dir()}
        image = (task.metadata or {}).get("docker_image")
        if image:
            if env.type == "local":
                raise ConfigError("local")
            update["image"] = image
        assert SingleAgentOrchestrator  # the code under test lives there
        return env.model_copy(update=update)

    def test_task_image_overrides_the_configured_one(self):
        task = Task(task_id="t", input="x", metadata={"docker_image": "img:task"})
        env = EnvironmentConfig(type="docker", image="img:default")
        assert self._env_for(task, env).image == "img:task"

    def test_configured_image_stands_when_the_task_has_none(self):
        task = Task(task_id="t", input="x", metadata={})
        env = EnvironmentConfig(type="docker", image="img:default")
        assert self._env_for(task, env).image == "img:default"

    def test_local_backend_refuses_a_task_that_needs_an_image(self):
        task = Task(task_id="t", input="x", metadata={"docker_image": "img:task"})
        with pytest.raises(ConfigError):
            self._env_for(task, EnvironmentConfig(type="local"))


class TestRealSeeds:
    def test_the_generated_swe_seeds_load_and_are_runnable(self):
        path = Path("data/seeds/swe_coding.jsonl")
        if not path.is_file():
            pytest.skip("swe_coding.jsonl not generated in this checkout")
        tasks = SWEBenchLocalDataset(path).load()
        assert len(tasks) == 200
        assert all(t.metadata["docker_image"] for t in tasks)
        assert all(t.reference for t in tasks)
