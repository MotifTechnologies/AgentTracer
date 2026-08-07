"""The timeouts a manifest declares, against a client that had none.

`StdioServerConfig` carries no timeout of any kind: upstream spawns the
process, awaits `initialize()` and awaits every `call_tool` unbounded. So
`startup_timeout_s` was never read at all and `call_timeout_s` reached only the
HTTP branch — `soffice`'s 180s was documentation, and the real limit on a
wedged server was the runner's task timeout, half an hour by default, twice
retried.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from stirrup.tools.mcp import MCPConfig, MCPToolProvider

from agent_tracer.mcp.discovery import MCPManifest
from agent_tracer.mcp.provider import TimeoutMCPToolProvider


def _manifest(name: str, **overrides: Any) -> MCPManifest:
    return MCPManifest.model_validate(
        {
            "manifest_version": 1,
            "name": name,
            "description": f"{name} test server",
            "transport": "stdio",
            "command": "uv",
            **overrides,
        }
    )


def _provider(manifests: dict[str, MCPManifest]) -> TimeoutMCPToolProvider:
    config = MCPConfig.model_validate(
        {"mcpServers": {name: {"command": "uv", "args": []} for name in manifests}}
    )
    return TimeoutMCPToolProvider(config, manifests)


class TestCallTimeout:
    def test_a_call_that_does_not_come_back_is_cut_off(self, monkeypatch):
        async def never(self, server, tool_name, arguments):
            await asyncio.sleep(30)

        monkeypatch.setattr(MCPToolProvider, "call_tool", never)
        provider = _provider({"soffice": _manifest("soffice", call_timeout_s=0.01)})

        answer = asyncio.run(provider.call_tool("soffice", "convert_document", {}))

        assert "timed out" in answer

    def test_the_model_is_told_rather_than_the_task_ended(self, monkeypatch):
        """The manifest's own description of what a timeout is: a tool result
        the agent loop continues from. Raising would lose the trajectory."""
        async def never(self, server, tool_name, arguments):
            await asyncio.sleep(30)

        monkeypatch.setattr(MCPToolProvider, "call_tool", never)
        provider = _provider({"soffice": _manifest("soffice", call_timeout_s=0.01)})

        answer = asyncio.run(provider.call_tool("soffice", "convert_document", {}))

        assert "soffice" in answer and "convert_document" in answer

    def test_a_call_that_answers_in_time_is_untouched(self, monkeypatch):
        async def quick(self, server, tool_name, arguments):
            return "rows"

        monkeypatch.setattr(MCPToolProvider, "call_tool", quick)
        provider = _provider({"sqlite": _manifest("sqlite", call_timeout_s=90)})

        assert asyncio.run(provider.call_tool("sqlite", "query", {})) == "rows"


class TestStartupTimeout:
    def test_a_handshake_that_never_completes_ends_the_attempt(self, monkeypatch):
        async def never(self):
            await asyncio.sleep(30)

        monkeypatch.setattr(MCPToolProvider, "__aenter__", never)
        provider = _provider({"alpha": _manifest("alpha", startup_timeout_s=0.01)})

        with pytest.raises(TimeoutError, match="startup_timeout_s"):
            asyncio.run(provider.__aenter__())

    def test_the_budget_is_every_selected_manifest_s(self, monkeypatch):
        """Upstream connects them in one sequential pass, so what can be
        enforced from outside it is the sum."""
        seen: list[float] = []

        async def measure(self):
            seen.append(asyncio.current_task().get_loop().time())
            return []

        monkeypatch.setattr(MCPToolProvider, "__aenter__", measure)
        provider = _provider(
            {
                "alpha": _manifest("alpha", startup_timeout_s=15),
                "beta": _manifest("beta", startup_timeout_s=20),
            }
        )

        assert provider._startup_budget() == 35
        assert asyncio.run(provider.__aenter__()) == []
