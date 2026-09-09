"""The sandbox is probed for every declared binary before the agent runs.

soffice hands its commands to `SandboxAccess.exec`, so a sandbox without the
binary used to fail only at the runtime tool call: the trajectory ended
normally with the tool quietly broken. These tests pin the replacement — a
`command -v` probe as soon as the task's sandbox is up, refusing the task
instead.

Driven through the local backend: `attach` there is the host shell, so the
probe path (describe → attach → exec) runs for real without Docker.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_tracer.config.schema import EnvironmentConfig
from agent_tracer.environments import SandboxMissingBinariesError
from agent_tracer.mcp.discovery import MCPManifest
from agent_tracer.orchestrators.single import SingleAgentOrchestrator

#: A name `command -v` will not find anywhere.
MISSING = "agent-tracer-no-such-binary"


def _manifest(name: str, binaries: list[str]) -> MCPManifest:
    return MCPManifest.model_validate(
        {
            "manifest_version": 1,
            "name": name,
            "description": f"{name} test server",
            "transport": "stdio",
            "command": "uv",
            "requires_binaries": binaries,
        }
    )


def _check(manifests: dict[str, MCPManifest], *, task_image: str | None = None) -> None:
    orch = SingleAgentOrchestrator(None, None, manifests=manifests, mcp_root=None)
    env_config = EnvironmentConfig(type="local")
    # The local backend's describe only reads `temp_dir` off the provider.
    provider = object()
    asyncio.run(orch._check_sandbox_binaries(env_config, provider, task_image))


class TestProbe:
    def test_a_present_binary_passes(self):
        _check({"alpha": _manifest("alpha", ["sh"])})

    def test_a_missing_binary_refuses_the_task(self):
        with pytest.raises(SandboxMissingBinariesError, match=MISSING):
            _check({"alpha": _manifest("alpha", [MISSING])})

    def test_the_error_names_the_server_that_wants_it(self):
        with pytest.raises(SandboxMissingBinariesError, match="alpha"):
            _check({"alpha": _manifest("alpha", [MISSING])})

    def test_only_the_missing_ones_are_reported(self):
        with pytest.raises(SandboxMissingBinariesError) as exc_info:
            _check({"alpha": _manifest("alpha", ["sh", MISSING])})
        assert MISSING in str(exc_info.value)
        assert "'sh'" not in str(exc_info.value)


class TestFatality:
    """Whose image is short decides how far the failure reaches."""

    def test_the_shared_config_image_dooms_the_run(self):
        with pytest.raises(SandboxMissingBinariesError) as exc_info:
            _check({"alpha": _manifest("alpha", [MISSING])}, task_image=None)
        assert exc_info.value.run_fatal is True

    def test_a_task_shipped_image_breaks_only_that_task(self):
        with pytest.raises(SandboxMissingBinariesError) as exc_info:
            _check({"alpha": _manifest("alpha", [MISSING])}, task_image="x/y:1")
        assert exc_info.value.run_fatal is False


class TestNothingDeclared:
    def test_no_requirements_probes_nothing(self):
        """Early return, proven by handing it a config no probe could use:
        describe on an unknown backend would raise before any exec."""
        orch = SingleAgentOrchestrator(
            None, None, manifests={"alpha": _manifest("alpha", [])}
        )
        env_config = EnvironmentConfig(type="no-such-backend", image="x")
        asyncio.run(orch._check_sandbox_binaries(env_config, None, None))

    def test_no_manifests_probes_nothing(self):
        orch = SingleAgentOrchestrator(None, None, manifests=None)
        env_config = EnvironmentConfig(type="no-such-backend", image="x")
        asyncio.run(orch._check_sandbox_binaries(env_config, None, None))
