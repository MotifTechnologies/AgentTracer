import pytest
from pydantic import ValidationError

from agent_tracer.config import ConfigError, load_config
from agent_tracer.config.schema import (
    EnvironmentConfig,
    MCPDiscoveryConfig,
    ModelConfig,
    RunnerConfig,
    resolve_env_ref,
)


def _model(**overrides):
    base = dict(
        model_name="m",
        base_url="http://x/v1",
        api_key="sk-literal",
        reasoning_key="reasoning",
    )
    base.update(overrides)
    return ModelConfig(**base)


class TestApiKey:
    def test_literal_key_passes_through(self):
        assert _model(api_key="sk-abc").resolved_api_key() == "sk-abc"

    def test_env_ref_resolves(self, monkeypatch):
        monkeypatch.setenv("AT_TEST_KEY", "sk-from-env")
        assert _model(api_key="env:AT_TEST_KEY").resolved_api_key() == "sk-from-env"

    def test_missing_env_refuses_to_run(self, monkeypatch):
        monkeypatch.delenv("AT_TEST_MISSING", raising=False)
        with pytest.raises(ConfigError, match="refusing to run"):
            _model(api_key="env:AT_TEST_MISSING").resolved_api_key()

    def test_empty_key_refuses_to_run(self):
        with pytest.raises(ConfigError, match="refusing to run"):
            resolve_env_ref("", field="model.api_key")


class TestEnvironmentOptions:
    """`options` is what `attach()` takes, so it is where a backend's key goes
    — a backend reads `api_key` out of it. It was handed on untouched, so
    `api_key: env:SANDBOX_KEY` passed that literal string to the backend
    and a plaintext key in the YAML was the only thing that worked."""

    def test_an_env_ref_resolves(self, monkeypatch):
        monkeypatch.setenv("AT_TEST_KEY", "sk-secret")
        config = EnvironmentConfig(
            type="docker", image="t", options={"api_key": "env:AT_TEST_KEY"}
        )

        assert config.resolved_options() == {"api_key": "sk-secret"}

    def test_a_literal_still_passes_through(self):
        config = EnvironmentConfig(
            type="docker", image="t", options={"user": "someone"}
        )

        assert config.resolved_options() == {"user": "someone"}

    def test_an_unset_ref_refuses_to_run(self, monkeypatch):
        monkeypatch.delenv("AT_TEST_MISSING_KEY", raising=False)
        config = EnvironmentConfig(
            type="docker", image="t", options={"api_key": "env:AT_TEST_MISSING_KEY"}
        )

        with pytest.raises(ConfigError, match="AT_TEST_MISSING_KEY"):
            config.resolved_options()


class TestReasoningKey:
    def test_reasoning_key_is_required(self):
        with pytest.raises(ValidationError):
            ModelConfig(model_name="m", base_url="http://x/v1", api_key="k")


class TestStrictness:
    def test_unknown_keys_rejected(self):
        with pytest.raises(ValidationError):
            RunnerConfig(max_docker_containers=8)

    def test_include_exclude_mutually_exclusive(self):
        with pytest.raises((ConfigError, ValidationError)):
            MCPDiscoveryConfig(include=["a"], exclude=["b"])


class TestLoadConfig:
    def _write(self, tmp_path, extra=""):
        cfg = tmp_path / "c.yaml"
        tasks = tmp_path / "t.jsonl"
        tasks.write_text('{"task_id": "t1", "input": "hi"}\n')
        cfg.write_text(
            f"""
dataset: {{name: custom, path: {tasks}}}
model:
  model_name: m
  base_url: http://x/v1
  api_key: sk-lit
  reasoning_key: none
{extra}
"""
        )
        return cfg

    def test_load_minimal(self, tmp_path):
        config = load_config(self._write(tmp_path))
        assert config.model.reasoning_key == "none"
        assert config.runner.max_concurrency == 8

    def test_dotted_override(self, tmp_path):
        config = load_config(self._write(tmp_path), ["runner.max_concurrency=3"])
        assert config.runner.max_concurrency == 3

    def test_bad_override_shape(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(self._write(tmp_path), ["runner.max_concurrency"])

    def test_an_environment_type_that_does_not_exist_is_refused(self, tmp_path):
        """`type` is a str rather than a Literal so a backend can be installed
        rather than merged, and nothing checked it until `build_provider` ran —
        inside `Runner._run_one`'s `except Exception`. A typo was a per-task
        failure retried three times, once for every task, instead of a config
        the run refuses to start with."""
        with pytest.raises(ConfigError, match="dokcer"):
            load_config(self._write(tmp_path, "environment: {type: dokcer, image: x}"))

    def test_a_backend_that_exists_still_loads(self, tmp_path):
        config = load_config(
            self._write(tmp_path, "environment: {type: docker, image: x}")
        )
        assert config.environment.type == "docker"

    def test_a_backend_option_that_cannot_be_resolved_is_refused_at_startup(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("AT_TEST_MISSING_KEY", raising=False)
        environment = (
            "environment: {type: docker, image: x, "
            "options: {api_key: 'env:AT_TEST_MISSING_KEY'}}"
        )

        with pytest.raises(ConfigError, match="AT_TEST_MISSING_KEY"):
            load_config(self._write(tmp_path, environment))
