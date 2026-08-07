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
import base64
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


def _no_bare_constants(name):
    """Python's JSON reader accepts `Infinity`; the JSON grammar does not."""
    raise AssertionError(f"the reply carries a bare {name}, which is not valid JSON")


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

        # `SELECT *` across a join is the query a model writes most often, and
        # it is the one that repeats a column name. Looking a row up by name
        # gives the first `id` twice, so the invoice's 77 would read as 1.
        await session.call_tool("execute", {"database": db,
            "sql": "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)"})
        await session.call_tool("execute", {"database": db,
            "sql": "INSERT INTO customers VALUES (1, 'Acme')"})
        await session.call_tool("execute", {"database": db,
            "sql": "CREATE TABLE invoices (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL)"})
        await session.call_tool("execute", {"database": db,
            "sql": "INSERT INTO invoices VALUES (77, 1, 12.5)"})
        out = _payload(await session.call_tool("query", {"database": db,
            "sql": "SELECT * FROM customers c JOIN invoices i ON i.customer_id = c.id"}))
        assert out["columns"] == ["id", "name", "id", "customer_id", "amount"], out
        assert out["rows"] == [[1, "Acme", 77, 1, 12.5]], out
        print("query SELECT * across a join -> ok, the duplicated id is 77 and not 1")

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

        # `query` reads. An INSERT through it reported zero rows and looked
        # like it had worked, and the connection was closed without committing.
        bad = await session.call_tool("query", {
            "database": db, "sql": "INSERT INTO orders (item, qty, price) VALUES ('X', 1, 1.0)"})
        assert bad.is_error, bad.content[0].text
        out = _payload(await session.call_tool("query", {
            "database": db, "sql": "SELECT COUNT(*) FROM orders"}))
        assert out["rows"] == [[3]], out
        print("query given a write -> refused, and the write did not happen")

        # `execute` writes. A SELECT through it threw the rows away and
        # answered with a rowcount instead.
        bad = await session.call_tool("execute", {"database": db, "sql": "SELECT * FROM orders"})
        assert bad.is_error, bad.content[0].text
        print("execute given a read -> refused")

        # A mistyped name created an empty database, and `list_tables` then
        # answered "no tables" — a database that is not there reading as one
        # that is empty.
        bad = await session.call_tool("list_tables", {"database": "typo.db"})
        assert bad.is_error, bad.content[0].text
        assert not (workdir / "typo.db").exists(), "a read created the database"
        print("list_tables on a mistyped name -> refused, and created nothing")

        # A BLOB is not text. Encoded with `default=str` it arrived as the
        # Python repr `b'\x00\x01\xff'` — a string the model reads as content.
        await session.call_tool("execute", {"database": db,
            "sql": "CREATE TABLE blobs (name TEXT, data BLOB)"})
        await session.call_tool("execute", {"database": db,
            "sql": "INSERT INTO blobs VALUES ('icon', x'0001FF')"})
        out = _payload(await session.call_tool("query", {
            "database": db, "sql": "SELECT data FROM blobs"}))
        cell = out["rows"][0][0]
        assert base64.b64decode(cell["blob_base64"]) == b"\x00\x01\xff", out
        assert cell["bytes"] == 3, out
        print("query on a BLOB -> ok, reversible rather than a Python repr")

        # SQLite evaluates 1e400 to +inf, and `json.dumps` writes that as a bare
        # `Infinity` token that a strict reader on the transport rejects.
        raw = (await session.call_tool("query", {
            "database": db, "sql": "SELECT 1e400 AS big"})).content[0].text
        json.loads(raw, parse_constant=_no_bare_constants)
        assert json.loads(raw)["rows"] == [[{"float": "Infinity"}]], raw
        print("query on a non-finite float -> ok, and the reply is valid JSON")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
