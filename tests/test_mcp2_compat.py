"""The mcp 2.x transport adapter, and the parts of it nothing else exercises.

Every other MCP test here is stdio or mocked, so the wrapper in `_mcp2_compat`
was never executed by the suite — which is how it shipped without closing the
httpx client it creates. These run it.
"""

from __future__ import annotations

import gc

import pytest

from agent_tracer.mcp import _mcp2_compat

pytest.importorskip("mcp")


class TestApplied:
    """`applied()` is the documented signal for deleting this module."""

    def test_reports_what_this_install_needed(self) -> None:
        _mcp2_compat.apply()

        # On mcp 2.x both names are gone and both get restored. On an mcp that
        # has them, this is empty and the module has no reason to exist.
        assert set(_mcp2_compat.applied()) <= {
            "streamablehttp_client",
            "Tool.inputSchema",
        }

    def test_applying_twice_changes_nothing(self) -> None:
        _mcp2_compat.apply()
        once = _mcp2_compat.applied()

        _mcp2_compat.apply()

        assert _mcp2_compat.applied() == once


class TestNamesStirrupNeeds:
    def test_the_transport_stirrup_imports_exists(self) -> None:
        _mcp2_compat.apply()
        from mcp.client import streamable_http

        assert hasattr(streamable_http, "streamablehttp_client")

    def test_the_tool_field_stirrup_reads_exists(self) -> None:
        _mcp2_compat.apply()
        from mcp.types import Tool

        tool = Tool(name="t", description="d", input_schema={"type": "object"})

        assert tool.inputSchema == {"type": "object"}

    def test_the_session_id_stand_in_refuses_rather_than_answering(self) -> None:
        """1.x yielded a real getter, and `None` was a legitimate answer from it
        — "no session yet". Returning None here would be indistinguishable from
        that. stirrup binds this to `_`; if anything starts calling it, it
        should say so."""
        with pytest.raises(_mcp2_compat.MCPCompatError, match="session-id"):
            _mcp2_compat._no_session_id()


class TestClientLifecycle:
    """The wrapper builds an httpx client and hands it to a transport that only
    closes clients it made itself. Whoever builds it has to close it."""

    @pytest.mark.anyio
    async def test_every_client_the_wrapper_builds_is_closed_again(self) -> None:
        """Entering and leaving the transport must leave nothing open. It used
        not to: `streamable_http_client` closes a client only when it made one,
        and this wrapper always supplies its own."""
        _mcp2_compat.apply()
        import httpx2
        from mcp.client import streamable_http

        created: list[httpx2.AsyncClient] = []
        real = streamable_http.create_mcp_http_client

        def spy(*args: object, **kwargs: object) -> httpx2.AsyncClient:
            client = real(*args, **kwargs)  # type: ignore[arg-type]
            created.append(client)
            return client

        streamable_http.create_mcp_http_client = spy  # type: ignore[assignment]
        try:
            # No request is made, so nothing has to be listening — the point is
            # what the context manager leaves behind.
            for _ in range(3):
                async with streamable_http.streamablehttp_client(
                    url="http://127.0.0.1:9/mcp", timeout=1, sse_read_timeout=1
                ):
                    pass
        finally:
            streamable_http.create_mcp_http_client = real  # type: ignore[assignment]

        gc.collect()
        assert created, "the wrapper never built a client, so this proves nothing"
        assert all(c.is_closed for c in created), (
            f"{sum(not c.is_closed for c in created)} of {len(created)} httpx clients "
            "were left open — the transport only closes ones it created itself"
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
