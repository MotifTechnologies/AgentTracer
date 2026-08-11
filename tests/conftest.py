"""Applies the mcp 2.x shim before any test module imports `stirrup.tools.mcp`.

The library applies it beside each of its own stirrup imports, but a test that
imports stirrup directly gets there first — third-party imports sort above
first-party ones.
"""

from agent_tracer.mcp import _mcp2_compat

_mcp2_compat.apply()
