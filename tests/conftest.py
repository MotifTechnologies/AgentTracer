"""Applies the mcp 2.x shim before any test module imports `stirrup.tools.mcp`.

`agent_tracer.mcp` does this for the library, but a test that imports stirrup
directly gets there first — third-party imports sort above first-party ones.
"""

import agent_tracer.mcp  # noqa: F401  — imported for its import-time effect
