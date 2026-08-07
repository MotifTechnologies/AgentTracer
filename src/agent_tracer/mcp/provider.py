"""stirrup's MCP client, holding each server to the timeouts it declares.

`StdioServerConfig` has no timeout of any kind. Upstream spawns the process,
awaits `initialize()`, and awaits every `call_tool` with nothing bounding it —
so a manifest's `startup_timeout_s` was never read and `call_timeout_s` reached
only the HTTP branch, whose config happens to carry one. `soffice`'s 180s was
documentation; the real limit was the runner's task timeout, half an hour by
default, and then two more attempts at the same wedged server.

Both are enforced here, around upstream rather than inside it, because the
connect loop and the tool executors are the two places a manifest's numbers can
still be reached without reimplementing either.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from stirrup.tools.mcp import MCPConfig, MCPToolProvider

if TYPE_CHECKING:
    from agent_tracer.mcp.discovery import MCPManifest


class TimeoutMCPToolProvider(MCPToolProvider):
    def __init__(self, config: MCPConfig, manifests: dict[str, MCPManifest]) -> None:
        super().__init__(config)
        self._manifests = manifests

    def _startup_budget(self) -> float:
        """What every selected manifest allows for its handshake, added up.

        Upstream connects the servers in one sequential pass, so a per-server
        bound is not reachable from out here; the sum is, and it is the same
        number as long as no server is slow.
        """
        return sum(m.startup_timeout_s for m in self._manifests.values())

    async def __aenter__(self) -> Any:
        budget = self._startup_budget()
        try:
            async with asyncio.timeout(budget or None):
                return await super().__aenter__()
        except TimeoutError as e:
            # Whatever was already connected is still on the exit stack.
            with suppress(Exception):
                await super().__aexit__(None, None, None)
            raise TimeoutError(
                f"an MCP server did not finish the initialize handshake within {budget}s "
                "(the sum of every selected manifest's startup_timeout_s). A server's "
                "first `uv run` builds its environment, which takes longer than that on "
                "a cold cache — warm it, or raise the manifest's startup_timeout_s."
            ) from e

    async def call_tool(self, server: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        manifest = self._manifests.get(server)
        timeout = manifest.call_timeout_s if manifest else None
        try:
            async with asyncio.timeout(timeout):
                return await super().call_tool(server, tool_name, arguments)
        except TimeoutError:
            # What the manifest says a timeout is: a tool result the model
            # reads and works around. Raising here would end the trajectory.
            return f"{server}/{tool_name} timed out after {timeout}s and was cancelled."
