"""MCP server discovery and the provider that runs them.

The mcp 2.x compatibility shim is applied here, before anything in this package
imports `stirrup.tools.mcp` — that import fails outright on mcp 2.x without it.
See `_mcp2_compat`; it is temporary.
"""

from agent_tracer.mcp import _mcp2_compat

_mcp2_compat.apply()
