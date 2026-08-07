"""The registry, and what a backend reports about a running sandbox.

`build` and `attach` need a real sandbox and are covered by each server's smoke
test. What is worth pinning here is the part that fails silently: `describe`
returning a plausible-but-wrong directory sends an MCP server looking for the
agent's files somewhere they are not, and the tool call comes back "no such
file" rather than failing where the mistake is.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_tracer.config.schema import ConfigError, EnvironmentConfig
from agent_tracer.environments import BUILTIN, _load, describe, from_env, resolve
from agent_tracer.mcp.discovery import SANDBOX_ENV_VARS, sandbox_env


def _cfg(**kw) -> EnvironmentConfig:
    kw.setdefault("type", "local")
    if kw["type"] != "local":
        kw.setdefault("image", "python:3.13-slim")
    return EnvironmentConfig(**kw)


class TestRegistry:
    def test_every_builtin_implements_the_whole_protocol(self):
        """A backend missing one of the three fails at the point it is used —
        `attach` only when an MCP server first calls a tool, which is late."""
        for name in BUILTIN:
            module = _load(name)
            for func in ("build", "describe", "attach"):
                assert callable(getattr(module, func, None)), f"{name}.{func} missing"

    def test_an_uninstalled_backend_names_the_ones_that_are(self):
        with pytest.raises(ConfigError) as e:
            describe(_cfg(type="no-such-backend"), None)
        message = str(e.value)
        assert "no-such-backend" in message
        for name in BUILTIN:
            assert name in message, f"{name} not offered as an alternative"


class TestDescribe:
    def test_local_reports_the_directory_commands_actually_run_in(self):
        """Not `working_dir`.

        stirrup's local provider makes its own temp directory and runs every
        command there, ignoring the configured value. A server that resolved a
        relative path against `/workspace` would miss the agent's files.
        """
        provider = SimpleNamespace(temp_dir="/tmp/local_exec_env_x")
        out = describe(_cfg(type="local", working_dir="/workspace"), provider)

        assert out["workdir"] == "/tmp/local_exec_env_x"
        assert out["host_dir"] == "/tmp/local_exec_env_x"
        assert out["sandbox_id"] is None

    def test_docker_reports_the_container_and_the_configured_workdir(self):
        provider = SimpleNamespace(container_id="abc123", temp_dir="/tmp/host")
        out = describe(_cfg(type="docker", working_dir="/workspace", user="user"), provider)

        assert out["sandbox_id"] == "abc123"
        assert out["workdir"] == "/workspace"
        assert out["host_dir"] == "/tmp/host"
        assert out["user"] == "user"

    def test_e2b_mounts_nothing_of_ours(self):
        provider = SimpleNamespace(_sbx=SimpleNamespace(sandbox_id="sbx_1"))
        out = describe(_cfg(type="e2b"), provider)

        assert out["sandbox_id"] == "sbx_1"
        assert out["host_dir"] is None

    def test_e2b_reports_the_root_stirrup_pins_it_to(self):
        """Not `working_dir`, whose default is `/workspace`.

        stirrup's E2B provider takes no working directory: it runs everything
        under its own `E2B_WORKING_DIR` and rejects paths outside it. A server
        resolving `data.csv` against the configured value would read
        `/workspace/data.csv` while code_exec had written `/home/user/data.csv`.
        """
        provider = SimpleNamespace(_sbx=SimpleNamespace(sandbox_id="sbx_1"))
        out = describe(_cfg(type="e2b", working_dir="/workspace"), provider)

        assert out["workdir"] == "/home/user"


class TestSandboxEnv:
    def test_every_documented_variable_can_be_produced(self):
        out = sandbox_env(
            env_type="docker",
            sandbox_id="abc",
            workdir="/workspace",
            host_dir="/tmp/host",
            user="user",
            options={"k": "v"},
        )
        assert set(out) == set(SANDBOX_ENV_VARS)

    def test_absent_beats_empty(self):
        """Servers test for presence; "" would read as a configured value."""
        out = sandbox_env(env_type="local", sandbox_id=None, workdir=None)

        assert out == {"AGENT_TRACER_ENV_TYPE": "local"}

    def test_describe_feeds_sandbox_env_directly(self):
        """The orchestrator splats one into the other — keep the names aligned."""
        provider = SimpleNamespace(container_id="abc123", temp_dir="/tmp/host")
        cfg = _cfg(type="docker", working_dir="/workspace", user="user")

        out = sandbox_env(env_type=cfg.type, options=cfg.options, **describe(cfg, provider))

        assert out["AGENT_TRACER_SANDBOX_ID"] == "abc123"
        assert out["AGENT_TRACER_WORKDIR"] == "/workspace"


class TestFromEnv:
    """The server side of the contract: reading back what the runner wrote."""

    def test_it_reads_what_sandbox_env_wrote(self):
        provider = SimpleNamespace(temp_dir="/tmp/local_exec_env_x")
        cfg = _cfg(type="local", working_dir="/workspace")
        written = sandbox_env(env_type=cfg.type, options=cfg.options, **describe(cfg, provider))

        _access, workdir = from_env(written)

        assert workdir == "/tmp/local_exec_env_x"

    def test_options_arrive_as_the_dict_they_were_sent_as(self):
        """They cross as a JSON string and are handed to `attach` untouched."""
        written = sandbox_env(env_type="local", options={"user": "someone"})

        assert written["AGENT_TRACER_OPTIONS"] == '{"user": "someone"}'
        assert from_env(written)[1]  # parses rather than raising

    def test_no_description_means_local_and_this_directory(self):
        """So a server can be run by hand — its smoke test depends on this."""
        import os

        access, workdir = from_env({})

        assert workdir == os.getcwd()
        assert access.exec("true")[0] == 0

    def test_resolve_leaves_absolute_paths_alone(self):
        assert resolve("data.csv", "/work") == "/work/data.csv"
        assert resolve("/etc/hosts", "/work") == "/etc/hosts"
        assert resolve("data.csv", "/work/") == "/work/data.csv"
