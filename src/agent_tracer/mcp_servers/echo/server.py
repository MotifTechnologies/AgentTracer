# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Reference MCP server for the agent-tracer MCP/ auto-discovery convention.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)
"""

from mcp.server import MCPServer

mcp = MCPServer(name="echo", version="0.1.0")


@mcp.tool()
def echo(text: str, repeat: int = 1) -> str:
    """Echo the given text back, optionally repeated.

    Args:
        text: The text to echo back.
        repeat: Number of times to repeat the text (1-10).
    """
    if not 1 <= repeat <= 10:
        raise ValueError("repeat must be between 1 and 10")
    return " ".join([text] * repeat)


if __name__ == "__main__":
    mcp.run(transport="stdio")
