"""The registry, and what a backend reports about a running sandbox.

`build` and `attach` need a real sandbox and are covered by each server's smoke
test. What is worth pinning here is the part that fails silently: `describe`
returning a plausible-but-wrong directory sends an MCP server looking for the
agent's files somewhere they are not, and the tool call comes back "no such
file" rather than failing where the mistake is.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import textwrap
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

    def test_attach_needs_nothing_only_the_runner_has(self):
        """A spawned MCP server has `agent_tracer` on PYTHONPATH and whatever it
        declares for itself. stirrup belongs to the runner that spawned it, so a
        backend importing its provider at module level makes `attach` unusable
        from a server: the first tool call on that backend dies with
        ModuleNotFoundError rather than doing the work.
        """
        script = textwrap.dedent(
            """
            import sys

            sys.modules["stirrup"] = None  # as absent as it is in a server

            from agent_tracer.environments import attach

            for backend in ("local", "docker", "e2b"):
                attach(backend, "some-id", {})
            """
        )
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=False
        )

        assert done.returncode == 0, done.stderr

    def test_an_uninstalled_backend_names_the_ones_that_are(self):
        with pytest.raises(ConfigError) as e:
            describe(_cfg(type="no-such-backend"), None)
        message = str(e.value)
        assert "no-such-backend" in message
        for name in BUILTIN:
            assert name in message, f"{name} not offered as an alternative"


class TestBuild:
    """What a backend does with a setting it cannot honour.

    Ignoring one is the worst of the three answers: `local` dropped
    `allowed_commands` and stirrup reads `None` as "every command allowed", so
    an explicit restriction became no restriction. `e2b` dropped `mem_limit`
    and `pids_limit`, so moving a config from docker to e2b lost both security
    caps and said nothing.
    """

    def test_local_passes_on_the_allowlist(self):
        provider = _load("local").build(_cfg(type="local", allowed_commands=["^python"]), task_id=None)

        assert provider._allowed_commands == ["^python"]

    def test_local_with_no_allowlist_stays_unrestricted(self):
        provider = _load("local").build(_cfg(type="local"), task_id=None)

        assert provider._allowed_commands is None

    def test_e2b_refuses_the_caps_it_cannot_apply(self):
        """Refused before the SDK is imported, so this is the answer whether or
        not the e2b extra is installed."""
        for cap in ({"mem_limit": "1g"}, {"pids_limit": 64}):
            with pytest.raises(ConfigError, match=next(iter(cap))):
                _load("e2b").build(_cfg(type="e2b", **cap), task_id=None)

    def test_e2b_is_not_refused_over_a_default_it_was_never_given(self):
        """The caps default to docker's values for every environment, so only a
        config that names one is refused."""
        with contextlib.suppress(ImportError):  # the e2b extra is optional
            _load("e2b").build(_cfg(type="e2b"), task_id=None)


class TestAttach:
    def test_docker_runs_a_plain_shell_not_a_login_shell(self, monkeypatch):
        """`sh -lc` sources /etc/profile and ~/.profile, and whatever they print
        lands on stdout — which is the channel every sandbox-bound server parses:
        base64 payloads in filesystem, NUL-separated records in list_directory,
        JSON in sqlite. A profile that echoes one line corrupts all three, and
        one that `cd`s moves what a relative path meant.

        It was also the only login shell in the project: stirrup's own code_exec
        runs `bash -c` and the local backend runs `sh -c`, so the agent and its
        tools saw two different environments on docker alone.
        """
        module = _load("docker")
        seen: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(module.subprocess, "run", fake_run)

        module.attach("abc123", {"user": "someone"}).exec("echo hi")

        assert seen["argv"] == [
            "docker", "exec", "--user", "someone", "abc123", "sh", "-c", "echo hi",
        ]


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

    def test_resolve_refuses_a_home_it_cannot_know(self):
        """`~` is the sandbox's home directory and this function has no way to
        learn it. Paths are shell-quoted on the way out, so a `~` survives as a
        literal: the read misses and the write makes a directory called `~`
        that nothing else looks in."""
        for path in ("~", "~/data.csv", "~someone/data.csv"):
            with pytest.raises(ValueError, match="~"):
                resolve(path, "/work")

    def test_resolve_refuses_an_empty_path(self):
        """`f"{workdir}/{''}"` is the working directory with a trailing slash,
        which reads as a successfully resolved path and is a missing argument."""
        with pytest.raises(ValueError):
            resolve("", "/work")

    def test_resolve_does_not_police_dot_dot(self):
        """Deliberate. Every tool documents its path as "absolute or relative to
        the working directory" and `/etc/hosts` is passed through above, so a
        containment check here would stop nothing a caller cannot do by writing
        the path out in full. The sandbox is the boundary, not this function."""
        assert resolve("../shared/data.csv", "/work") == "/work/../shared/data.csv"
