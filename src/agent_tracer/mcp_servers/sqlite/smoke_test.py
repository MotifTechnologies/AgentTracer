# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the sqlite server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/sqlite && uv run smoke_test.py

`AGENT_TRACER_ENV_TYPE` unset means the local backend, so the in-sandbox
`python3 -c` really is executed — the same path a container takes, pointed at
this machine.

PYTHONPATH is set for the same reason the runner sets it: the server calls
`environments.from_env()` and so has to import the package, from a `uv run` that
does not inherit this interpreter.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())


def _payload(result):
    return json.loads(result.content[0].text)


async def main() -> None:
    workdir = Path(tempfile.mkdtemp())

    params = StdioServerParameters(
        command=MANIFEST["command"],
        args=MANIFEST["args"],
        cwd=str(HERE),
        env={
            "AGENT_TRACER_WORKDIR": str(workdir),
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(HERE.parents[2]),
        },
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print(f"discovered tools: {names}")
        declared = [t["name"] for t in MANIFEST.get("tools", [])]
        assert set(declared) <= set(names), f"manifest declares {declared}, server exposes {names}"

        db = "sales.db"
        await session.call_tool("execute", {
            "database": db,
            "sql": "CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT NOT NULL, qty INTEGER, price REAL)",
        })
        for item, qty, price in [("연필", 3, 1.1), ("공책", 2, 2.2), ("지우개", 10, 0.55)]:
            out = _payload(await session.call_tool("execute", {
                "database": db,
                "sql": "INSERT INTO orders (item, qty, price) VALUES (?, ?, ?)",
                "params": [item, qty, price],
            }))
            assert out["rows_affected"] == 1, out
        print("execute (DDL + parameterised inserts) -> ok")

        out = _payload(await session.call_tool("list_tables", {"database": db}))
        assert [t["name"] for t in out["tables"]] == ["orders"], out
        print("list_tables -> ok")

        out = _payload(await session.call_tool("describe_table", {"database": db, "table": "orders"}))
        cols = {c["name"]: c for c in out["columns"]}
        assert cols["id"]["primary_key"] and cols["item"]["not_null"], out
        print("describe_table -> ok, primary key and NOT NULL reported")

        # The point of the server: an aggregate the model would otherwise do in
        # its head, and non-ASCII values surviving the JSON round trip.
        out = _payload(await session.call_tool("query", {
            "database": db, "sql": "SELECT item, qty * price AS total FROM orders ORDER BY total DESC"}))
        assert out["columns"] == ["item", "total"], out
        assert out["rows"][0] == ["지우개", 5.5], out  # 10 * 0.55, ordered first
        assert out["row_count"] == 3 and not out["truncated"], out
        print(f"query -> ok, {out['rows']}")

        out = _payload(await session.call_tool("query", {
            "database": db, "sql": "SELECT * FROM orders", "max_rows": 2}))
        assert out["row_count"] == 2 and out["truncated"], out
        print("query max_rows -> truncated and says so")

        out = _payload(await session.call_tool("query", {
            "database": db, "sql": "SELECT item FROM orders WHERE qty > ?", "params": [5]}))
        assert [r[0] for r in out["rows"]] == ["지우개"], out
        print("query placeholders -> ok, an int stays an int")

        # SQLite's own message has to reach the model — it is what the next
        # attempt is built from.
        bad = await session.call_tool("query", {"database": db, "sql": "SELECT * FROM nope"})
        assert bad.is_error and "no such table" in bad.content[0].text, bad.content[0].text
        print("unknown table -> refused, message passed through")

        bad = await session.call_tool("query", {"database": db, "sql": "SELEC bad syntax"})
        assert bad.is_error and "syntax error" in bad.content[0].text.lower(), bad.content[0].text
        print("syntax error -> refused, message passed through")

        bad = await session.call_tool("describe_table", {"database": db, "table": "nope"})
        assert bad.is_error and "No such table" in bad.content[0].text, bad.content[0].text
        print("describe_table on unknown table -> refused")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
