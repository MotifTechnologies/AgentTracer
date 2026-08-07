# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the filesystem server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/filesystem && uv run smoke_test.py

`AGENT_TRACER_ENV_TYPE` unset means the local backend, so this runs against a
real temp directory — every command goes through the same `SandboxAccess.exec`
the sandboxed backends use, only pointed at this machine.

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
    (workdir / "note.txt").write_text("alpha\nbravo\ncharlie\n", encoding="utf-8")
    (workdir / "sub").mkdir()
    (workdir / "sub" / "data.csv").write_text("id,name\n1,중간보고서\n", encoding="utf-8")
    # Not valid UTF-8. Reading it must not kill the call.
    (workdir / "raw.bin").write_bytes(b"\xff\xfe binary \x00 bytes")
    # A latin-1 CSV — the everyday not-quite-UTF-8 file. An edit to one row
    # must leave every other byte exactly as it was.
    (workdir / "latin.csv").write_bytes(b"id,name\n1,caf\xe9\n2,na\xefve\n")

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

        out = _payload(await session.call_tool("read_file", {"path": "note.txt"}))
        assert out["content"] == "alpha\nbravo\ncharlie", out
        assert out["total_lines"] == 3 and not out["truncated"], out
        print("read_file -> ok")

        out = _payload(await session.call_tool("read_file", {"path": "note.txt", "offset": 1, "limit": 1}))
        assert out["content"] == "bravo" and out["truncated"], out
        print("read_file paging -> ok, and says it truncated")

        # Non-UTF-8 must come back marked, not blow up the call.
        out = _payload(await session.call_tool("read_file", {"path": "raw.bin"}))
        assert "�" in out["content"], out
        print("read_file on non-UTF-8 -> replaced, not crashed")

        # `str.splitlines()` breaks on \x0b \x0c \x1c-\x1e \x85     and
        # a bare \r as well as \n, and the window is rejoined with \n. A file
        # holding any of them was counted as more lines than it has, paged by
        # the wrong boundaries, and shown to the model as bytes it does not
        # contain. A form feed is ordinary in a printable text file.
        (workdir / "feeds.txt").write_text("one\x0ctwo\nthree\x0bfour\n", encoding="utf-8")
        out = _payload(await session.call_tool("read_file", {"path": "feeds.txt"}))
        assert out["total_lines"] == 2, out
        assert out["content"] == "one\x0ctwo\nthree\x0bfour", out
        out = _payload(await session.call_tool("read_file", {"path": "feeds.txt", "offset": 1}))
        assert out["content"] == "three\x0bfour", out
        print("read_file -> ok, splits on newlines and nothing else")

        # Korean has to survive the base64 round trip in both directions.
        await session.call_tool("write_file", {"path": "sub/new.txt", "content": "한글 내용\n둘째 줄\n"})
        out = _payload(await session.call_tool("read_file", {"path": "sub/new.txt"}))
        assert out["content"] == "한글 내용\n둘째 줄", out
        print("write_file/read_file round trip -> ok, non-ASCII intact")

        # write_file creates missing parents.
        await session.call_tool("write_file", {"path": "deep/deeper/x.txt", "content": "x"})
        assert (workdir / "deep" / "deeper" / "x.txt").read_text() == "x"
        print("write_file creates parents -> ok")

        out = _payload(await session.call_tool("edit_file", {
            "path": "note.txt", "old_string": "bravo", "new_string": "BRAVO"}))
        assert out["replacements"] == 1, out
        assert (workdir / "note.txt").read_text() == "alpha\nBRAVO\ncharlie\n"
        print("edit_file -> ok")

        # The refusals are the point of the tool: an ambiguous or absent match
        # must not be applied, and the message has to say which it was.
        (workdir / "dup.txt").write_text("x\nx\n", encoding="utf-8")
        bad = await session.call_tool("edit_file", {"path": "dup.txt", "old_string": "x", "new_string": "y"})
        assert bad.is_error and "2 times" in bad.content[0].text, bad.content[0].text
        assert (workdir / "dup.txt").read_text() == "x\nx\n", "an ambiguous edit was applied anyway"
        print("edit_file ambiguous -> refused, file untouched")

        out = _payload(await session.call_tool("edit_file", {
            "path": "dup.txt", "old_string": "x", "new_string": "y", "replace_all": True}))
        assert out["replacements"] == 2 and (workdir / "dup.txt").read_text() == "y\ny\n"
        print("edit_file replace_all -> ok")

        bad = await session.call_tool("edit_file", {
            "path": "note.txt", "old_string": "not-there", "new_string": "z"})
        assert bad.is_error and "does not appear" in bad.content[0].text, bad.content[0].text
        print("edit_file no match -> refused")

        # This tool exists because a bad `sed -i` corrupts a file silently.
        # Decoding with errors="replace" and writing the result back does the
        # same thing: every byte that is not UTF-8 becomes U+FFFD, including in
        # the rows the edit never mentioned.
        out = _payload(await session.call_tool("edit_file", {
            "path": "latin.csv", "old_string": "1,", "new_string": "9,"}))
        assert out["replacements"] == 1, out
        assert (workdir / "latin.csv").read_bytes() == b"id,name\n9,caf\xe9\n2,na\xefve\n", \
            (workdir / "latin.csv").read_bytes()
        print("edit_file on a latin-1 file -> ok, the untouched rows are byte-identical")

        out = _payload(await session.call_tool("list_directory", {"path": "."}))
        kinds = {e["name"]: e["type"] for e in out["entries"]}
        assert kinds["sub"] == "directory" and kinds["note.txt"] == "file", kinds
        print("list_directory -> ok, directories marked")

        # `ls` on a plain file lists the file, so this came back as a directory
        # holding exactly one entry whose name was the whole absolute path.
        bad = await session.call_tool("list_directory", {"path": "note.txt"})
        assert bad.is_error, bad.content[0].text
        assert "not a directory" in bad.content[0].text.lower(), bad.content[0].text
        bad = await session.call_tool("list_directory", {"path": "nope-dir"})
        assert bad.is_error, bad.content[0].text
        print("list_directory on a file -> refused, and says which it was")

        out = _payload(await session.call_tool("file_info", {"path": "note.txt"}))
        assert out["size_bytes"] > 0 and "file" in out["type"], out
        print("file_info -> ok")

        out = _payload(await session.call_tool("search_files", {"pattern": "*.csv"}))
        assert any(m.endswith("sub/data.csv") for m in out["matches"]), out
        print("search_files -> ok")

        out = _payload(await session.call_tool("search_content", {"pattern": "중간보고서"}))
        assert out["count"] == 1 and out["matches"][0]["line"] == 2, out
        print("search_content -> ok, line numbers and non-ASCII")

        # The docstring says "File or directory", and grep drops the filename
        # prefix when given exactly one file operand — even under -r. Parsed on
        # that prefix, the match disappears and the tool reports count 0.
        out = _payload(await session.call_tool("search_content", {
            "pattern": "중간보고서", "path": "sub/data.csv"}))
        assert out["count"] == 1, out
        assert out["matches"][0]["line"] == 2, out
        assert out["matches"][0]["path"].endswith("sub/data.csv"), out
        print("search_content on one file -> ok, the match is not dropped")

        # No matches is an answer, not a failure — grep exits 1 for it.
        out = _payload(await session.call_tool("search_content", {"pattern": "zzz-nothing"}))
        assert out["count"] == 0, out
        print("search_content no matches -> empty, not an error")

        # `head` ends the pipeline, so the exit code that comes back is head's
        # and find's or grep's is lost. A directory that is not there read
        # exactly like a directory with nothing in it.
        for tool in ("search_files", "search_content"):
            bad = await session.call_tool(tool, {"pattern": "*", "path": "no/such/dir"})
            assert bad.is_error, f"{tool}: {bad.content[0].text}"
        print("search on a path that is not there -> refused, not answered 'none'")

        # A negative cap became `head -n -1`, which prints all but the last line
        # — a truncated answer presented as the whole one.
        for tool in ("search_files", "search_content"):
            for cap in (-1, 0):
                bad = await session.call_tool(tool, {"pattern": "a", "max_results": cap})
                assert bad.is_error, f"{tool} max_results={cap}: {bad.content[0].text}"
        print("search with max_results < 1 -> refused")

        # Matches were split on ":" into path, line, text. A colon in the
        # filename put a fragment of the name where the line number goes, and
        # int() on it killed the call.
        (workdir / "we:ird.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
        out = _payload(await session.call_tool("search_content", {"pattern": "needle here"}))
        assert out["count"] == 1, out
        assert out["matches"][0]["line"] == 2, out
        assert out["matches"][0]["path"].endswith("we:ird.txt"), out
        print("search_content with a colon in the path -> ok")

        await session.call_tool("create_directory", {"path": "made/up"})
        assert (workdir / "made" / "up").is_dir()
        await session.call_tool("move_file", {"source": "note.txt", "destination": "made/up/moved.txt"})
        assert (workdir / "made" / "up" / "moved.txt").exists() and not (workdir / "note.txt").exists()
        print("create_directory/move_file -> ok")

        missing = await session.call_tool("read_file", {"path": "nope.txt"})
        assert missing.is_error, missing.content[0].text
        print("missing file -> refused")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
