# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3", "pypdf>=6,<7", "pdfplumber>=0.11,<0.12"]
# ///
"""Reading PDFs that are in the task's sandbox.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

`soffice` converts *to* PDF well and reads *from* it badly — LibreOffice opens a
PDF as a drawing, so text comes back reflowed or not at all. Extraction is a
different job, and this is it.

The alternative is the model writing `python3 -c "import pypdf; ..."` in the
sandbox, which needs pypdf installed there, fails differently per image, and
records page-slicing boilerplate in the trajectory instead of the step. Here the
libraries are declared in this script's own header and the sandbox only has to
produce bytes.

So the PDF is read out of the sandbox (`environments.read_bytes`, base64 over
`exec`) and parsed in this process. Nothing is written back — extraction does
not modify the document, and generating a PDF is `soffice`'s job.

Two libraries because they are good at different things: pypdf for text,
metadata and page geometry, pdfplumber for tables, which pypdf does not do.
"""

import io

from mcp.server import MCPServer

from agent_tracer.environments import from_env, read_bytes, resolve

mcp = MCPServer(name="pdf", version="0.1.0")

DEFAULT_TIMEOUT_S = 120

#: A page range wider than this arrives as one tool result and takes the context
#: window with it. The reply says when it truncated so the model can page.
MAX_PAGES_PER_CALL = 50

#: Same reasoning for a single enormous page (a poster, a scanned plan).
MAX_CHARS_PER_PAGE = 20_000

_SANDBOX = None


def _sandbox():
    """The sandbox and its working directory, opened once and reused."""
    global _SANDBOX
    if _SANDBOX is None:
        _SANDBOX = from_env()
    return _SANDBOX


def _load(path: str) -> tuple[str, bytes]:
    """Resolve `path` against the working directory and fetch its bytes."""
    access, workdir = _sandbox()
    target = resolve(path, workdir)
    return target, read_bytes(access, target, timeout_s=DEFAULT_TIMEOUT_S)


def _reader(raw: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw))
    except PdfReadError as exc:
        raise ValueError(f"Not a readable PDF: {exc}") from exc

    if reader.is_encrypted:
        # An empty user password is the common case for "protected" documents
        # and costs one call to rule out.
        try:
            opened = reader.decrypt("")
        except Exception:  # noqa: BLE001 — any failure here means the same thing
            opened = 0
        if not opened:
            raise ValueError("This PDF is encrypted and needs a password, which this tool cannot supply.")
    return reader


def _page_span(reader, first_page: int, last_page: int | None) -> tuple[int, int, bool]:
    """Clamp a 1-based inclusive request onto what the document has."""
    total = len(reader.pages)
    if first_page < 1:
        raise ValueError("first_page is 1-based; it must be >= 1")
    if first_page > total:
        raise ValueError(f"first_page {first_page} is past the end — the document has {total} pages")

    end = total if last_page is None else min(last_page, total)
    if end < first_page:
        raise ValueError("last_page must not be before first_page")

    capped = min(end, first_page + MAX_PAGES_PER_CALL - 1)
    return first_page, capped, capped < end


@mcp.tool()
def pdf_info(path: str) -> dict:
    """Page count, metadata and page size of a PDF.

    Worth calling first: `extract_text` returns at most
    50 pages, and this says how many there are.

    Args:
        path: PDF file, absolute or relative to the working directory.
    """
    target, raw = _load(path)
    reader = _reader(raw)
    meta = reader.metadata or {}

    first = reader.pages[0] if reader.pages else None
    box = first.mediabox if first is not None else None
    return {
        "path": target,
        "pages": len(reader.pages),
        "size_bytes": len(raw),
        "encrypted": bool(reader.is_encrypted),
        "metadata": {
            k.lstrip("/"): str(v)
            for k, v in meta.items()
            if v is not None and str(v).strip()
        },
        # In points (72 per inch); a task asking about layout needs this and it
        # is otherwise invisible from the text alone.
        "page_size_pt": (
            {"width": round(float(box.width), 1), "height": round(float(box.height), 1)}
            if box is not None
            else None
        ),
    }


@mcp.tool()
def extract_text(path: str, first_page: int = 1, last_page: int | None = None) -> dict:
    """Extract text from a PDF, one page range at a time.

    Pages come back separately rather than as one blob, because a question about
    a document is usually a question about a page of it and a citation needs a
    number.

    Args:
        path: PDF file, absolute or relative to the working directory.
        first_page: First page to extract, 1-based and inclusive.
        last_page: Last page, inclusive. Defaults to the end of the document.
    """
    target, raw = _load(path)
    reader = _reader(raw)
    start, end, truncated = _page_span(reader, first_page, last_page)

    pages, empty = [], []
    for number in range(start, end + 1):
        text = reader.pages[number - 1].extract_text() or ""
        if not text.strip():
            empty.append(number)
        clipped = text[:MAX_CHARS_PER_PAGE]
        pages.append(
            {
                "page": number,
                "text": clipped,
                "char_count": len(text),
                # Per page, because the document as a whole is the wrong unit:
                # one stamped or watermarked page in a scan is enough to make
                # every other page's "" look like a page that is genuinely blank.
                "empty": not text.strip(),
                "truncated": len(text) > MAX_CHARS_PER_PAGE,
            }
        )

    listed = ", ".join(str(number) for number in empty[:20])
    return {
        "path": target,
        "total_pages": len(reader.pages),
        "pages": pages,
        "truncated": truncated,
        # A scan has pages and no text. Saying so beats returning "" and letting
        # the model conclude the document is blank — and it has to be said when
        # *any* page is empty, not only when they all are. A 50-page scan with a
        # stamp on one page is still a scan.
        "note": (
            f"{len(empty)} of {len(pages)} requested pages held no extractable text "
            f"(page{'s' if len(empty) > 1 else ''} {listed}{', ...' if len(empty) > 20 else ''}). "
            "Those are likely scanned and need OCR rather than extraction; their `text` "
            "is \"\" because nothing could be read, not because the page is blank."
            if empty
            else None
        ),
    }


@mcp.tool()
def extract_tables(path: str, first_page: int = 1, last_page: int | None = None) -> dict:
    """Extract tables from a PDF as rows of cells.

    A table read out of `extract_text` arrives as columns run together, which is
    where numbers get misread. This keeps the cells apart.

    Args:
        path: PDF file, absolute or relative to the working directory.
        first_page: First page to search, 1-based and inclusive.
        last_page: Last page, inclusive. Defaults to the end of the document.
    """
    import pdfplumber

    target, raw = _load(path)
    reader = _reader(raw)
    start, end, truncated = _page_span(reader, first_page, last_page)

    tables = []
    with pdfplumber.open(io.BytesIO(raw)) as doc:
        for number in range(start, end + 1):
            for index, table in enumerate(doc.pages[number - 1].extract_tables()):
                tables.append(
                    {
                        "page": number,
                        "index": index,
                        # None means an empty cell; "" reads as a value that is
                        # there and blank, which is a different claim.
                        "rows": [[cell if cell is not None else "" for cell in row] for row in table],
                        "row_count": len(table),
                        "column_count": max((len(r) for r in table), default=0),
                    }
                )

    return {"path": target, "tables": tables, "count": len(tables), "truncated": truncated}


@mcp.tool()
def search_text(
    path: str,
    pattern: str,
    case_sensitive: bool = False,
    max_results: int = 50,
    first_page: int = 1,
    last_page: int | None = None,
) -> dict:
    """Find which pages contain a string, and show the surrounding text.

    For locating a clause or figure in a long document without extracting all of
    it first. Searches at most 50 pages per call, like the other tools here: a
    pattern that never matches would otherwise extract every page of a
    3,000-page PDF, past the call timeout and with the stdio server blocked for
    everything else meanwhile. `truncated` says when there is more to search.

    Args:
        path: PDF file, absolute or relative to the working directory.
        pattern: Literal text to look for. Not a regular expression.
        case_sensitive: Match case exactly.
        max_results: Stop after this many matches.
        first_page: First page to search, 1-based and inclusive.
        last_page: Last page, inclusive. Defaults to the end of the document.
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")

    target, raw = _load(path)
    reader = _reader(raw)
    start, end, truncated = _page_span(reader, first_page, last_page)
    needle = pattern if case_sensitive else pattern.lower()

    matches = []
    for number in range(start, end + 1):
        text = reader.pages[number - 1].extract_text() or ""
        haystack = text if case_sensitive else text.lower()
        position = haystack.find(needle)
        while position != -1 and len(matches) < max_results:
            matches.append(
                {
                    "page": number,
                    "context": " ".join(
                        text[max(0, position - 90) : position + len(pattern) + 90].split()
                    ),
                }
            )
            position = haystack.find(needle, position + len(needle))
        if len(matches) >= max_results:
            break

    return {
        "path": target,
        "pattern": pattern,
        "matches": matches,
        "count": len(matches),
        "pages_with_matches": sorted({m["page"] for m in matches}),
        "total_pages": len(reader.pages),
        "first_page": start,
        "last_page": end,
        "truncated": truncated,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
