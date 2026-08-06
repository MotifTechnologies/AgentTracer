# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the echo server over stdio (as the runner would) and call its tool.

    cd MCP/echo && uv run smoke_test.py
"""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MANIFEST = json.loads((Path(__file__).parent / "mcp.json").read_text())


async def main() -> None:
    params = StdioServerParameters(
        command=MANIFEST["command"],
        args=MANIFEST["args"],
        cwd=str(Path(__file__).parent),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"discovered tools: {names}")
            declared = [t["name"] for t in MANIFEST.get("tools", [])]
            assert set(declared) <= set(names), f"manifest declares {declared}, server exposes {names}"

            result = await session.call_tool("echo", {"text": "ping", "repeat": 3})
            output = result.content[0].text
            print(f"echo('ping', repeat=3) -> {output!r}")
            assert output == "ping ping ping", output

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
