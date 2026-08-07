# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3", "reportlab>=4,<5"]
# ///
"""Smoke test: spawn the pdf server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/pdf && uv run smoke_test.py

Builds a real three-page PDF first — Korean and ASCII text, a ruled table, and a
page with no text on it at all — then drives every tool against it. reportlab is
a fixture dependency and is not what the server uses.

`AGENT_TRACER_ENV_TYPE` unset means the local backend, so the bytes really do
travel through `SandboxAccess.exec` and base64, the same path a container takes.

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

TITLE = "중간보고서 초안"
BODY = "Agent trajectory dataset, phase two."
NEEDLE = "phase two"
TABLE = [
    ["item", "qty", "unit_price"],
    ["pencil", "3", "1100"],
    ["notebook", "2", "2200"],
    ["eraser", "10", "550"],
]


def _payload(result):
    return json.loads(result.content[0].text)


def _build_pdf(path: Path) -> None:
    """Three pages: text, a ruled table, and one deliberately without text."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(TITLE)
    c.setAuthor("agent-tracer")

    c.setFont("HYSMyeongJo-Medium", 16)
    c.drawString(60, 780, TITLE)
    c.setFont("Helvetica", 11)
    c.drawString(60, 750, BODY)
    c.showPage()

    # Ruled, because pdfplumber's default strategy finds tables by their lines.
    c.setFont("Helvetica", 10)
    x0, y0, w, h = 60, 700, 120, 20
    for row, cells in enumerate(TABLE):
        for col, cell in enumerate(cells):
            c.rect(x0 + col * w, y0 - row * h, w, h)
            c.drawString(x0 + col * w + 4, y0 - row * h + 6, cell)
    c.showPage()

    # A rectangle and nothing else — stands in for a scan.
    c.rect(100, 500, 200, 120, fill=0)
    c.showPage()
    c.save()


def _build_long_pdf(path: Path, pages: int = 60) -> None:
    """Longer than `MAX_PAGES_PER_CALL`, so a clamp is visible at all.

    `search_text` had no page cap: a pattern that does not match extracted every
    page of the document, which for a 3,000-page PDF blows past the manifest's
    180s `call_timeout_s` and blocks the single-threaded stdio server for every
    other call.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for number in range(1, pages + 1):
        c.setFont("Helvetica", 12)
        c.drawString(60, 780, f"page {number} of {pages}")
        c.showPage()
    c.save()


async def main() -> None:
    workdir = Path(tempfile.mkdtemp())
    _build_pdf(workdir / "report.pdf")
    _build_long_pdf(workdir / "long.pdf")
    (workdir / "not-a.pdf").write_text("plain text, not a PDF\n", encoding="utf-8")
    print(f"fixture: {(workdir / 'report.pdf').stat().st_size} bytes")

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

        out = _payload(await session.call_tool("pdf_info", {"path": "report.pdf"}))
        assert out["pages"] == 3, out
        assert out["metadata"].get("Title") == TITLE, out
        assert not out["encrypted"], out
        # A4 is 595 x 842 pt.
        assert round(out["page_size_pt"]["width"]) == 595, out
        print(f"pdf_info -> ok, {out['pages']} pages, title={out['metadata'].get('Title')!r}")

        out = _payload(await session.call_tool("extract_text", {"path": "report.pdf"}))
        assert out["total_pages"] == 3 and len(out["pages"]) == 3, out
        page1 = out["pages"][0]["text"]
        assert TITLE in page1, page1
        assert BODY in page1, page1
        print("extract_text -> ok, Korean survived base64 + extraction")

        # One page of text does not make the other pages readable. The note
        # fired only when *every* requested page was empty, so a 50-page scan
        # with a stamp on one page returned `note: null` and 49 pages of "".
        assert out["note"] and "page 3" in out["note"], out["note"]
        assert out["pages"][2]["empty"] and not out["pages"][0]["empty"], out["pages"]
        print("extract_text over a mixed range -> names the pages that held no text")

        out = _payload(await session.call_tool(
            "extract_text", {"path": "report.pdf", "first_page": 1, "last_page": 2}))
        assert out["note"] is None, out["note"]
        print("extract_text over pages that all have text -> no note")

        out = _payload(await session.call_tool(
            "extract_text", {"path": "report.pdf", "first_page": 2, "last_page": 2}))
        assert [p["page"] for p in out["pages"]] == [2], out
        assert "notebook" in out["pages"][0]["text"], out
        print("extract_text page range -> ok, page numbers preserved")

        # The scanned-document case: pages exist, text does not. Returning ""
        # silently would let the model conclude the document is blank.
        out = _payload(await session.call_tool(
            "extract_text", {"path": "report.pdf", "first_page": 3}))
        assert out["note"] and "scanned" in out["note"], out
        print("extract_text on a text-free page -> says it is likely a scan")

        out = _payload(await session.call_tool("extract_tables", {"path": "report.pdf"}))
        assert out["count"] >= 1, out
        rows = out["tables"][0]["rows"]
        header = [c.strip() for c in rows[0]]
        assert header == TABLE[0], rows
        # The point of the tool: cells stay apart, so 3 and 1100 are two values.
        body = [[c.strip() for c in r] for r in rows[1:]]
        assert ["pencil", "3", "1100"] in body, body
        print(f"extract_tables -> ok, {out['tables'][0]['row_count']}x{out['tables'][0]['column_count']}")

        out = _payload(await session.call_tool(
            "search_text", {"path": "report.pdf", "pattern": NEEDLE}))
        assert out["pages_with_matches"] == [1], out
        assert NEEDLE in out["matches"][0]["context"], out
        print("search_text -> ok, found on the right page with context")

        out = _payload(await session.call_tool(
            "search_text", {"path": "report.pdf", "pattern": "중간보고서"}))
        assert out["count"] == 1, out
        print("search_text non-ASCII -> ok")

        out = _payload(await session.call_tool(
            "search_text", {"path": "report.pdf", "pattern": "PHASE TWO", "case_sensitive": True}))
        assert out["count"] == 0, out
        print("search_text case_sensitive -> ok, no false match")

        # A pattern that never matches used to extract every page of the
        # document, however long it was — the one tool here with no page cap.
        out = _payload(await session.call_tool(
            "search_text", {"path": "long.pdf", "pattern": "no-such-string"}))
        assert out["count"] == 0 and out["truncated"], out
        assert (out["first_page"], out["last_page"]) == (1, 50), out
        print("search_text on a 60-page document -> clamped to 50 pages and says so")

        out = _payload(await session.call_tool(
            "search_text", {"path": "long.pdf", "pattern": "page 55", "first_page": 51}))
        assert out["pages_with_matches"] == [55], out
        assert not out["truncated"], out
        print("search_text with a page range -> reaches the rest of the document")

        bad = await session.call_tool("extract_text", {"path": "not-a.pdf"})
        assert bad.is_error and "PDF" in bad.content[0].text, bad.content[0].text
        print("not a PDF -> refused")

        bad = await session.call_tool("pdf_info", {"path": "missing.pdf"})
        assert bad.is_error, bad.content[0].text
        print("missing file -> refused")

        bad = await session.call_tool("extract_text", {"path": "report.pdf", "first_page": 99})
        assert bad.is_error and "3 pages" in bad.content[0].text, bad.content[0].text
        print("page past the end -> refused, and says how many there are")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
