# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3", "openpyxl>=3.1,<4"]
# ///
"""Smoke test: spawn the xlsx server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/xlsx && uv run smoke_test.py

Builds a two-sheet workbook with Korean sheet names, a formula, a date and a
hidden sheet, then drives every tool against it. openpyxl appears here as a
fixture builder and as the check on what was actually written.

The cases worth asserting are the two that produce confidently wrong answers: a
formula cell whose cached value is absent (it must not read as an empty cell),
and a lossy round trip (a workbook with a chart must be refused, not silently
stripped).

`AGENT_TRACER_ENV_TYPE` unset means the local backend, so the bytes really do
travel through `SandboxAccess.exec` and base64 in both directions.
"""

import asyncio
import datetime as dt
import json
import os
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())

SHEET = "매출"
ROWS = [("pencil", 3, 1100), ("notebook", 2, 2200), ("eraser", 10, 550)]


def _payload(result):
    return json.loads(result.content[0].text)


def _build(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws["A1"], ws["B1"], ws["C1"], ws["D1"] = "item", "qty", "unit_price", "total"
    for i, (item, qty, price) in enumerate(ROWS, start=2):
        ws[f"A{i}"], ws[f"B{i}"], ws[f"C{i}"] = item, qty, price
        ws[f"D{i}"] = f"=B{i}*C{i}"
    ws["A6"] = "합계"
    ws["D6"] = "=SUM(D2:D4)"
    ws["A8"] = "as of"
    # Naive on purpose: an .xlsx cell has no timezone to carry.
    ws["B8"] = dt.datetime(2026, 8, 6, 9, 30)  # noqa: DTZ001

    notes = wb.create_sheet("notes")
    notes["A1"] = "draft"
    hidden = wb.create_sheet("internal")
    hidden["A1"] = "hidden sheet"
    hidden.sheet_state = "hidden"
    wb.save(path)


def _build_sparse(path: Path) -> None:
    """Two cells, 4.8 KB, and a used range of 2.08 million coordinates.

    openpyxl instantiates a Cell for every coordinate in the used range when it
    is not in read-only mode, so `list(sheet.iter_rows())` — on two workbook
    copies, which is what reading formulas and values costs — turns this file
    into gigabytes. The server runs outside the sandbox with no cgroup limit,
    so a 4.8 KB file could take the runner host down with it.
    """
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "corner"
    ws["CZ20000"] = "far"
    wb.save(path)


def _build_with_chart(path: Path) -> None:
    import openpyxl
    from openpyxl.chart import BarChart, Reference

    wb = openpyxl.Workbook()
    ws = wb.active
    for i, (item, qty, _) in enumerate(ROWS, start=1):
        ws[f"A{i}"], ws[f"B{i}"] = item, qty
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=3))
    ws.add_chart(chart, "D2")
    wb.save(path)


async def main() -> None:
    workdir = Path(tempfile.mkdtemp())
    _build(workdir / "sales.xlsx")
    _build_with_chart(workdir / "charted.xlsx")
    _build_sparse(workdir / "sparse.xlsx")
    (workdir / "not-a.xlsx").write_text("plain text\n", encoding="utf-8")

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

        out = _payload(await session.call_tool("list_sheets", {"path": "sales.xlsx"}))
        by_name = {s["name"]: s for s in out["sheets"]}
        assert set(by_name) == {SHEET, "notes", "internal"}, out
        assert by_name["internal"]["hidden"] and not by_name[SHEET]["hidden"], out
        print(f"list_sheets -> ok, {list(by_name)}, hidden flagged")

        out = _payload(await session.call_tool("read_range", {"path": "sales.xlsx"}))
        cells = {c["ref"]: c for c in out["cells"]}
        assert out["sheet"] == SHEET, out
        assert cells["A2"]["value"] == "pencil", cells["A2"]
        assert cells["A6"]["value"] == "합계", cells["A6"]
        # Empty cells are skipped rather than returned as nulls.
        assert "A7" not in cells, cells

        # The trap: D2 holds a formula and no cached value. It must come back
        # with the formula and a note, not as a blank cell.
        assert cells["D2"]["formula"] == "=B2*C2", cells["D2"]
        assert cells["D2"]["value"] is None, cells["D2"]
        assert out["note"] and "never calculated" in out["note"], out["note"]
        print("read_range -> ok, uncomputed formulas reported rather than read as blank")

        # Dates must be JSON, not a repr of a datetime.
        assert cells["B8"]["value"] == "2026-08-06 09:30:00", cells["B8"]
        print(f"read_range date -> {cells['B8']['value']}")

        out = _payload(await session.call_tool(
            "read_range", {"path": "sales.xlsx", "cell_range": "A1:C1"}))
        assert [c["ref"] for c in out["cells"]] == ["A1", "B1", "C1"], out
        assert out["note"] is None, out
        print("read_range with a range -> ok")

        out = _payload(await session.call_tool(
            "read_range", {"path": "sales.xlsx", "cell_range": "D6"}))
        assert [c["ref"] for c in out["cells"]] == ["D6"], out
        print("read_range single cell -> ok")

        out = _payload(await session.call_tool("read_range", {"path": "sales.xlsx", "sheet": "notes"}))
        assert out["sheet"] == "notes" and out["cells"][0]["value"] == "draft", out
        print("read_range other sheet -> ok")

        out = _payload(await session.call_tool(
            "find_cells", {"path": "sales.xlsx", "pattern": "eraser"}))
        assert out["count"] == 1 and out["matches"][0]["ref"] == "A4", out
        assert out["matches"][0]["sheet"] == SHEET, out
        print("find_cells -> ok, searches every sheet and reports which")

        out = _payload(await session.call_tool(
            "find_cells", {"path": "sales.xlsx", "pattern": "SUM"}))
        assert any(m["formula"] == "=SUM(D2:D4)" for m in out["matches"]), out
        print("find_cells matches formulas too -> ok")

        # A 4.8 KB file must not cost the host gigabytes. The window is capped
        # before anything is materialised, and skipped cells count towards it.
        started = time.monotonic()
        out = _payload(await session.call_tool("read_range", {"path": "sparse.xlsx"}))
        elapsed = time.monotonic() - started
        assert out["truncated"], out
        assert out["count"] <= 2000, out["count"]
        assert not any(c["ref"] == "CZ20000" for c in out["cells"]), "walked the whole used range"
        assert out["range"].endswith(":CZ19"), out["range"]  # 2000 // 104 columns
        assert elapsed < 15, f"took {elapsed:.1f}s — the used range was materialised"
        print(f"read_range over a 2.08M-coordinate used range -> {out['range']}, {elapsed:.2f}s")

        out = _payload(await session.call_tool(
            "read_range", {"path": "sparse.xlsx", "cell_range": "A1:CZ20000"}))
        assert out["truncated"] and out["count"] <= 2000, out
        print("read_range with an oversized explicit range -> capped the same way")

        started = time.monotonic()
        out = _payload(await session.call_tool(
            "find_cells", {"path": "sparse.xlsx", "pattern": "no-such-label"}))
        elapsed = time.monotonic() - started
        assert out["count"] == 0 and out["truncated"], out
        assert out["note"] and "scan" in out["note"], out["note"]
        assert elapsed < 15, f"took {elapsed:.1f}s"
        print(f"find_cells with no match -> stops on its scan budget, {elapsed:.2f}s")

        # Write, then verify against the file itself rather than the reply.
        out = _payload(await session.call_tool("write_cells", {
            "path": "sales.xlsx", "cells": {"B2": 5, "E1": "검수", "D8": "=D6*2"}}))
        assert out["written"] == ["B2", "D8", "E1"], out
        import openpyxl

        wb = openpyxl.load_workbook(workdir / "sales.xlsx")
        assert wb[SHEET]["B2"].value == 5, "the write did not reach the file"
        assert wb[SHEET]["E1"].value == "검수"
        assert wb[SHEET]["D8"].value == "=D6*2", "a leading = must be stored as a formula"
        # Untouched cells and the other sheets have to survive the round trip.
        assert wb[SHEET]["A2"].value == "pencil" and wb[SHEET]["D6"].value == "=SUM(D2:D4)"
        assert set(wb.sheetnames) == {SHEET, "notes", "internal"}
        assert wb["internal"].sheet_state == "hidden"
        print("write_cells -> ok, targeted; other cells, sheets and hidden state intact")

        bad = await session.call_tool("write_cells", {"path": "charted.xlsx", "cells": {"A1": "x"}})
        assert bad.is_error and "chart" in bad.content[0].text, bad.content[0].text
        print("write_cells on a charted workbook -> refused rather than silently stripping it")

        bad = await session.call_tool("read_range", {"path": "sales.xlsx", "sheet": "nope"})
        assert bad.is_error and SHEET in bad.content[0].text, bad.content[0].text
        print("unknown sheet -> refused, and lists the real ones")

        bad = await session.call_tool("list_sheets", {"path": "not-a.xlsx"})
        assert bad.is_error, bad.content[0].text
        print("not a workbook -> refused")

        bad = await session.call_tool("write_cells", {"path": "sales.xlsx", "cells": {}})
        assert bad.is_error and "at least one" in bad.content[0].text, bad.content[0].text
        print("empty write -> refused")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
