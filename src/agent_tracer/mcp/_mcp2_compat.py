"""A transport adapter that lets stirrup 0.2.0 run on mcp 2.x.

This was written as a short-lived bridge and is not one. stirrup cannot move to
mcp 2.x while its `all` extra pulls `browser-use`, which pins `mcp==1.26.0`
exactly — so this file stays until either that pin loosens or stirrup drops the
extra. Treat it as code we own, not as a stopgap: it is on the path of every
`transport: http` MCP server we run.

mcp 2.x renamed two things stirrup reaches for. Each patch below restores the
old name pointed at its replacement:

    mcp.client.streamable_http.streamablehttp_client   -> streamable_http_client
    mcp.types.Tool.inputSchema                         -> Tool.input_schema

The transport wrapper is a port of the one mcp 1.29 ships for the same purpose
(`mcp/client/streamable_http.py`), kept deliberately close to it so the two can
be diffed. The lifecycle line is the part that matters: `streamable_http_client`
closes the httpx client only when it made the client itself, so a caller that
supplies one owns it.

`applied()` reports which patches this install needed. When it returns nothing
on a supported install, delete this module and its call sites.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: Names patched on this install, in application order.
_applied: list[str] = []


class MCPCompatError(RuntimeError):
    """The shim could not be applied, and the reason is not a missing mcp."""


def applied() -> list[str]:
    """Which patches this install needed. Empty means the module can go."""
    return list(_applied)


def _patch_streamable_http() -> None:
    """Restore the pre-2.x transport name, in the shape stirrup unpacks."""
    from mcp.client import streamable_http

    if hasattr(streamable_http, "streamablehttp_client"):
        return

    import httpx2

    @asynccontextmanager
    async def streamablehttp_client(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        sse_read_timeout: float = 300,
        terminate_on_close: bool = True,
    ) -> AsyncIterator[tuple[Any, Any, Any]]:
        client = streamable_http.create_mcp_http_client(
            headers=headers,
            # `sse_read_timeout` bounded reads before, so it stays the read timeout.
            timeout=httpx2.Timeout(timeout, read=sse_read_timeout),
        )
        # We made the client, so we close it. `streamable_http_client` only
        # takes ownership of one it created itself, and without this every
        # connection leaks a client and its pool — including the ones that end
        # in a timeout or an unreachable server.
        async with (
            client,
            streamable_http.streamable_http_client(
                url=url, http_client=client, terminate_on_close=terminate_on_close
            ) as streams,
        ):
            yield streams[0], streams[1], _no_session_id

    streamable_http.streamablehttp_client = streamablehttp_client
    _applied.append("streamablehttp_client")


def _no_session_id() -> str | None:
    """Stand-in for the session-id getter 1.x yielded third.

    It raises rather than returning None. `None` was a legitimate answer there —
    it meant the session had not been established yet — so returning it would be
    indistinguishable from a real one. stirrup binds this value to `_` and never
    calls it; if that ever changes, this should be loud.
    """
    raise MCPCompatError(
        "The session-id getter is not available through the mcp 2.x compatibility "
        "shim (agent_tracer.mcp._mcp2_compat). Nothing called it when the shim was "
        "written; a caller that needs it needs the real transport."
    )


def _patch_tool_input_schema() -> None:
    """Restore `Tool.inputSchema`, which 2.x renamed to `input_schema`."""
    import mcp.types

    if hasattr(mcp.types.Tool, "inputSchema"):
        return

    mcp.types.Tool.inputSchema = property(lambda self: self.input_schema)  # type: ignore[attr-defined]
    _applied.append("Tool.inputSchema")


def _needed() -> bool:
    """Whether the installed mcp is missing anything stirrup reaches for."""
    import mcp.types
    from mcp.client import streamable_http

    return not hasattr(streamable_http, "streamablehttp_client") or not hasattr(
        mcp.types.Tool, "inputSchema"
    )


def apply() -> None:
    """Install whichever patches the installed mcp needs. Safe to call twice.

    Raises:
        MCPCompatError: if mcp is installed but the shim cannot be applied. A
            missing mcp is left alone — stirrup's own error covers that case
            correctly, and this module has nothing to say about it.
    """
    if _applied:
        return
    if importlib.util.find_spec("mcp") is None:
        return
    try:
        if not _needed():
            return
    except Exception as exc:
        raise MCPCompatError(
            f"Could not inspect the installed mcp: {type(exc).__name__}: {exc}"
        ) from exc
    if "stirrup.tools.mcp" in sys.modules:
        # Only reachable where stirrup imported successfully and still needs a
        # patch — an mcp that dropped a name after stirrup had bound it. On the
        # mcp this module exists for, that import fails outright and never
        # reaches sys.modules, so this is a guard against a future, not the
        # ordering hazard a caller is likely to hit. That one is documented.
        raise MCPCompatError(
            "stirrup.tools.mcp was imported before this shim could be applied, so "
            "it is already bound to names the installed mcp does not have. Import "
            "agent_tracer.mcp.provider before importing stirrup.tools.mcp."
        )
    try:
        _patch_streamable_http()
        _patch_tool_input_schema()
    except Exception as exc:
        raise MCPCompatError(
            f"Could not adapt the installed mcp for stirrup: {type(exc).__name__}: {exc}"
        ) from exc
