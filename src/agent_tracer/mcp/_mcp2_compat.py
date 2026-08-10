"""Let stirrup 0.2.0 import and run under mcp 2.x.

**Temporary. Delete this module when stirrup supports mcp 2.x itself.**

The MCP SDK went to 2.0 and renamed two things stirrup reaches for at import
time and at run time. stirrup's own extra is `mcp>=1.9.0` with no upper bound,
so a fresh install already resolves 2.x and then cannot import — the failure
even reports itself as a missing extra, because the `except ImportError` around
those imports assumes that is the only reason to land there.

Nothing here changes what stirrup does. Each patch restores a name 2.x removed,
pointed at its replacement:

    mcp.client.streamable_http.streamablehttp_client   -> streamable_http_client
    mcp.types.Tool.inputSchema                         -> Tool.input_schema

Both are guarded on absence, so this becomes a no-op the moment the installed
mcp — or a newer stirrup — provides them. That is the signal to remove it: when
`applied()` returns nothing on a supported install, the module has no reason to
exist.

It has to run before anything imports `stirrup.tools.mcp`, which is why
`agent_tracer.mcp.__init__` applies it rather than the modules that use it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

_applied: list[str] = []


def applied() -> list[str]:
    """Which shims this install actually needed. Empty means none of it is."""
    return list(_applied)


def _patch_streamable_http() -> None:
    """Restore the pre-2.x transport name, in the shape stirrup unpacks.

    2.x renamed the function, replaced `headers`/`timeout`/`sse_read_timeout`
    with a prepared httpx client, and dropped the third yielded value. stirrup
    unpacks three and discards the last, so the wrapper supplies a stand-in
    rather than pretending to carry a session id it has no way to read.
    """
    from mcp.client import streamable_http

    if hasattr(streamable_http, "streamablehttp_client"):
        return

    # 2.x vendors httpx as `httpx2`; the Timeout has to come from the same one.
    httpx = getattr(streamable_http, "httpx2", None) or streamable_http.httpx

    @asynccontextmanager
    async def streamablehttp_client(
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
        sse_read_timeout: float = 300,
        terminate_on_close: bool = True,
        **_ignored: Any,
    ) -> Any:
        client = streamable_http.create_mcp_http_client(
            headers=headers,
            # `sse_read_timeout` bounded reads before, so it stays the read timeout.
            timeout=httpx.Timeout(timeout, read=sse_read_timeout),
        )
        async with streamable_http.streamable_http_client(
            url=url, http_client=client, terminate_on_close=terminate_on_close
        ) as streams:
            # Third value was a session-id getter. stirrup binds it to `_`; if a
            # future stirrup reads it, this shim is the wrong answer and the
            # right one is the upstream fix this module is waiting for.
            yield streams[0], streams[1], lambda: None

    streamable_http.streamablehttp_client = streamablehttp_client
    _applied.append("streamablehttp_client")


def _patch_tool_input_schema() -> None:
    """Restore `Tool.inputSchema`, which 2.x renamed to `input_schema`."""
    import mcp.types

    if hasattr(mcp.types.Tool, "inputSchema"):
        return

    mcp.types.Tool.inputSchema = property(lambda self: self.input_schema)  # type: ignore[attr-defined]
    _applied.append("Tool.inputSchema")


def apply() -> None:
    """Install whichever shims the installed mcp needs. Safe to call twice."""
    if _applied:
        return
    try:
        _patch_streamable_http()
        _patch_tool_input_schema()
    except ImportError:
        # No mcp at all: the extra is genuinely missing, and stirrup's own error
        # says so correctly. Nothing to shim.
        return
