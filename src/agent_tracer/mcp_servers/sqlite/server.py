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
import base64, json, math, os, sqlite3, sys
from pathlib import Path

def cell(value):
    # Explicit, not `default=str`: that rendered a BLOB as the Python repr
    # b'\x00\x01\xff', which the model reads as the bytes' content, and left
    # +-inf as a bare `Infinity` token that is not valid JSON.
    if isinstance(value, bytes):
        return {"blob_base64": base64.b64encode(value).decode("ascii"), "bytes": len(value)}
    if isinstance(value, float) and not math.isfinite(value):
        return {"float": "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")}
    return value

req = json.loads(base64.b64decode(sys.argv[1]))
mode = req["mode"]
try:
    database = os.path.abspath(req["database"])
    if mode == "query":
        # Opened read-only, and never created. A read that can write commits
        # nothing and loses it; a read that creates answers "no tables" for a
        # database that was only ever a typo.
        if not os.path.exists(database):
            raise FileNotFoundError("no such database")
        con = sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True, timeout=10)
    else:
        con = sqlite3.connect(database, timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(req["sql"], req.get("params") or [])
    # `description` is the only reliable answer to "did this return rows", and
    # each tool has to be given the kind of statement it commits for.
    if mode == "query":
        if cur.description is None:
            raise ValueError("this statement returns no rows - use execute to write")
        rows = cur.fetchmany(req["max_rows"] + 1)
        truncated = len(rows) > req["max_rows"]
        rows = rows[: req["max_rows"]]
        out = {
            "columns": [d[0] for d in cur.description],
            # list(row), not a lookup per key: a join repeats column names and
            # Row resolves a name to the first column holding it, so every
            # duplicate would report the first one's value.
            "rows": [[cell(v) for v in r] for r in rows],
            "truncated": truncated,
        }
    else:
        if cur.description is not None:
            raise ValueError(
                "this statement returns rows - use query to read. A write with RETURNING "
                "is not supported here; run it without the RETURNING clause"
            )
        con.commit()
        out = {"rows_affected": cur.rowcount, "last_row_id": cur.lastrowid}
    con.close()
    # allow_nan=False so a value `cell` did not account for fails loudly here
    # rather than leaving a bare token in the reply.
    print(json.dumps({"ok": True, "result": out}, allow_nan=False))
except Exception as exc:
    message = f"{type(exc).__name__}: {exc}"
    if mode == "query" and isinstance(exc, sqlite3.OperationalError) and "readonly" in str(exc):
        # What the read-only connection refused, said in terms of the tools.
        message = "this statement writes - query only reads, use execute"
    print(json.dumps({"ok": False, "error": message}))
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

    # Parsing is not the same as being ours. Whatever else the sandbox printed
    # last — a login shell's banner, a wrapper's own output — parses too when it
    # happens to be JSON, and indexing it raised TypeError from here rather than
    # the message that quotes what was actually on stdout.
    if not isinstance(reply, dict) or "ok" not in reply:
        raise RuntimeError(f"Unexpected output from the sandbox: {out.strip()[:300]}")

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

    The database is opened read-only and is not created: a statement that
    writes, or a name that does not exist, is refused rather than answered.

    Args:
        database: Path to an existing .db file, absolute or relative to the
            working directory.
        sql: A single SELECT (or PRAGMA) statement that returns rows.
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
        database: Path to an existing .db file, absolute or relative to the
            working directory.
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
        database: Path to an existing .db file, absolute or relative to the
            working directory.
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
