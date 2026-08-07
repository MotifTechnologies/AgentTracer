# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Querying a SQLite database in the task's sandbox.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

The same argument as `calculator`, at the scale where it matters more. Asked to
total a column or join two tables, a model without this reads the file and does
the arithmetic in its head, and is confidently wrong often enough to matter. A
query is checkable; a paragraph of mental arithmetic is not.

Runs `python3` inside the sandbox rather than the `sqlite3` CLI. The CLI is
absent from most slim images, and `sqlite3` is in the Python standard library —
in a sandbox built to execute code, the interpreter is the safer assumption.

`query` and `execute` are separate tools even though one function could do both.
The split puts "this step read" and "this step wrote" in the trajectory as
different tool names, which is worth more than the saved tool slot.
"""

import base64
import json
import shlex

from mcp.server import MCPServer

from agent_tracer.environments import from_env, resolve

mcp = MCPServer(name="sqlite", version="0.1.0")

#: What SQLite can bind to a `?`. Not `list[str]` — a quantity is an integer and
#: a price is a float, and coercing them to text changes what the query means.
SqlParams = list[str | int | float | bool | None] | None

DEFAULT_TIMEOUT_S = 60

#: Caps a `SELECT *` on a large table, which would otherwise arrive as one tool
#: result and take the context window with it.
DEFAULT_MAX_ROWS = 200

_SANDBOX = None

# Runs in the sandbox. Reads one JSON request on argv and writes one JSON reply,
# so nothing about the caller's SQL has to survive a shell quoting round trip —
# it travels base64-encoded inside the request.
_RUNNER = r"""
import base64, json, sqlite3, sys

req = json.loads(base64.b64decode(sys.argv[1]))
try:
    con = sqlite3.connect(req["database"], timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(req["sql"], req.get("params") or [])
    if req["mode"] == "query":
        rows = cur.fetchmany(req["max_rows"] + 1)
        truncated = len(rows) > req["max_rows"]
        rows = rows[: req["max_rows"]]
        out = {
            "columns": [d[0] for d in cur.description] if cur.description else [],
            # list(row), not a lookup per key: a join repeats column names and
            # Row resolves a name to the first column holding it, so every
            # duplicate would report the first one's value.
            "rows": [list(r) for r in rows],
            "truncated": truncated,
        }
    else:
        con.commit()
        out = {"rows_affected": cur.rowcount, "last_row_id": cur.lastrowid}
    con.close()
    print(json.dumps({"ok": True, "result": out}, default=str))
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
"""


def _sandbox():
    """The sandbox and its working directory, opened once and reused."""
    global _SANDBOX
    if _SANDBOX is None:
        _SANDBOX = from_env()
    return _SANDBOX


def _call(database: str, sql: str, params: SqlParams, mode: str, max_rows: int = 0) -> dict:
    """Run one statement in the sandbox and return its result."""
    target = resolve(database, _sandbox()[1])
    request = base64.b64encode(
        json.dumps(
            {
                "database": target,
                "sql": sql,
                "params": params,
                "mode": mode,
                "max_rows": max_rows,
            }
        ).encode("utf-8")
    ).decode("ascii")

    command = f"python3 -c {shlex.quote(_RUNNER)} {shlex.quote(request)}"
    rc, out, err = _sandbox()[0].exec(command, timeout_s=DEFAULT_TIMEOUT_S)
    if rc != 0:
        detail = (err.strip() or out.strip())[:300]
        raise RuntimeError(f"Could not run python3 in the sandbox: {detail}")

    try:
        reply = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"Unexpected output from the sandbox: {out.strip()[:300]}") from exc

    if not reply["ok"]:
        # SQLite's own message — "no such table: x", "syntax error near ..." —
        # is what the model needs to fix the query, so it is passed through.
        raise ValueError(f"{reply['error']} (database: {target})")
    return reply["result"]


@mcp.tool()
def query(
    database: str,
    sql: str,
    params: SqlParams = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict:
    """Run a read query and return the rows.

    Args:
        database: Path to the .db file, absolute or relative to the working
            directory. Created empty if it does not exist.
        sql: A single SELECT (or PRAGMA) statement.
        params: Values for `?` placeholders, in order. Use these rather than
            formatting values into the SQL.
        max_rows: Stop after this many rows; the reply says if it truncated.
    """
    if max_rows < 1:
        raise ValueError("max_rows must be >= 1")
    result = _call(database, sql, params, mode="query", max_rows=max_rows)
    result["row_count"] = len(result["rows"])
    return result


@mcp.tool()
def execute(database: str, sql: str, params: SqlParams = None) -> dict:
    """Run a statement that changes the database, and commit it.

    For INSERT, UPDATE, DELETE and DDL. Reads go through `query`.

    Args:
        database: Path to the .db file, absolute or relative to the working
            directory. Created empty if it does not exist.
        sql: A single statement.
        params: Values for `?` placeholders, in order.
    """
    return _call(database, sql, params, mode="execute")


@mcp.tool()
def list_tables(database: str) -> dict:
    """List the tables and views in a database.

    Args:
        database: Path to the .db file, absolute or relative to the working
            directory.
    """
    result = _call(
        database,
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name",
        None,
        mode="query",
        max_rows=1000,
    )
    return {"tables": [{"name": r[0], "type": r[1]} for r in result["rows"]]}


@mcp.tool()
def describe_table(database: str, table: str) -> dict:
    """Show a table's columns, their types and which are the primary key.

    Args:
        database: Path to the .db file, absolute or relative to the working
            directory.
        table: Table name.
    """
    # `table` cannot be a `?` placeholder — PRAGMA takes an identifier, not a
    # value — so it is quoted as one, which is what makes it safe here.
    identifier = '"' + table.replace('"', '""') + '"'
    result = _call(database, f"PRAGMA table_info({identifier})", None, mode="query", max_rows=1000)
    if not result["rows"]:
        raise ValueError(f"No such table in {database}: {table}")

    columns = [
        {
            "name": r[1],
            "type": r[2],
            "not_null": bool(r[3]),
            "default": r[4],
            "primary_key": bool(r[5]),
        }
        for r in result["rows"]
    ]
    return {"table": table, "columns": columns}


if __name__ == "__main__":
    mcp.run(transport="stdio")
