# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the calculator server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/calculator && uv run smoke_test.py
"""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())

EXACT = [
    ("1 + 1", "2"),
    ("0.1 + 0.2", "0.3"),  # the reason this is Decimal and not float
    ("(1.1 + 2.2) * 3", "9.9"),
    ("7 // 2", "3"),
    ("2 ** 10", "1024"),
    ("-3 + 5", "2"),
    # 61 digits. Formatted as a plain integer, a rounded answer here is
    # indistinguishable from the real one — the failure the tool is for.
    ("2 ** 200", str(2**200)),
]

REFUSED = [
    "__import__('os').system('id')",
    "open('/etc/passwd').read()",
    "1 + x",
    "1 / 0",
    "9 ** 99999",
    "1 +",
]


async def main() -> None:
    params = StdioServerParameters(
        command=MANIFEST["command"], args=MANIFEST["args"], cwd=str(HERE)
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print(f"discovered tools: {names}")
        declared = [t["name"] for t in MANIFEST.get("tools", [])]
        assert set(declared) <= set(names), f"manifest declares {declared}, server exposes {names}"

        for expression, expected in EXACT:
            result = await session.call_tool("calculate", {"expression": expression})
            assert not result.is_error, result.content[0].text
            payload = json.loads(result.content[0].text)
            got = payload["result"]
            assert got == expected, f"{expression} -> {got!r}, expected {expected!r}"
            assert payload["exact"], f"{expression} -> reported inexact"
            print(f"  {expression:<18} = {got}")

        # A division that does not terminate cannot be written out, so it is
        # rounded — and has to say so rather than read as the whole answer.
        payload = json.loads(
            (await session.call_tool("calculate", {"expression": "1 / 3"})).content[0].text
        )
        assert not payload["exact"], payload
        assert payload["result"].startswith("0.333333"), payload
        print(f"  1 / 3 rounded, and reports exact={payload['exact']}")

        for expression in REFUSED:
            result = await session.call_tool("calculate", {"expression": expression})
            assert result.is_error, f"{expression!r} was not refused"
        print(f"refused all {len(REFUSED)}: names, calls, division by zero, huge powers, syntax")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
