import pytest
from pydantic import ValidationError

from agent_tracer.config import ConfigError, load_config
from agent_tracer.config.schema import (
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
