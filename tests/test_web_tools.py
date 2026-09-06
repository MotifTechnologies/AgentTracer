"""`tools.web` without a Brave key is refused at startup.

Upstream's WebToolProvider adds web_search only when a key is present, and
says nothing when it is not: the agent gets web_fetch alone, every trajectory
in the run carries a tool set nobody asked for, and the run exits clean.
"""

import pytest

from agent_tracer.config.schema import ConfigError, ToolsConfig


class TestKeyResolution:
    def test_config_env_reference_wins(self, monkeypatch):
        monkeypatch.setenv("AT_BRAVE", "from-config-ref")
        monkeypatch.setenv("BRAVE_API_KEY", "from-environment")
        tools = ToolsConfig(web=True, brave_api_key="env:AT_BRAVE")
        assert tools.resolved_brave_key() == "from-config-ref"

    def test_a_literal_is_taken_as_written(self):
        assert (
            ToolsConfig(web=True, brave_api_key="bsk-literal").resolved_brave_key()
            == "bsk-literal"
        )

    def test_environment_is_the_fallback(self, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "from-environment")
        assert ToolsConfig(web=True).resolved_brave_key() == "from-environment"

    def test_nothing_anywhere_is_none(self, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        assert ToolsConfig(web=True).resolved_brave_key() is None

    def test_an_unset_reference_still_aborts(self, monkeypatch):
        monkeypatch.delenv("AT_MISSING_BRAVE", raising=False)
        with pytest.raises(ConfigError, match="AT_MISSING_BRAVE"):
            ToolsConfig(
                web=True, brave_api_key="env:AT_MISSING_BRAVE"
            ).resolved_brave_key()


class TestStartupRefusal:
    def _config(self, tmp_path, tools_block: str):
        from agent_tracer.config import load_config

        tasks = tmp_path / "t.jsonl"
        tasks.write_text('{"task_id": "t1", "input": "x"}\n')
        cfg = tmp_path / "c.yaml"
        cfg.write_text(
            f"dataset: {{name: custom, path: {tasks}}}\n"
            "model: {model_name: m, base_url: 'http://x/v1', api_key: k, reasoning_key: none}\n"
            f"{tools_block}\n"
        )
        return load_config(cfg)

    def test_web_without_a_key_refuses_to_run(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="Brave Search key"):
            self._config(tmp_path, "tools: {web: true}")

    def test_web_with_a_key_loads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAVE_API_KEY", "bsk-x")
        assert self._config(tmp_path, "tools: {web: true}").tools.web is True

    def test_web_off_needs_no_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        assert self._config(tmp_path, "tools: {web: false}").tools.web is False
