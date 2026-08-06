# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the soffice server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/soffice && uv run smoke_test.py

Runs against the local filesystem — `AGENT_TRACER_ENV_TYPE` unset means local,
which is the one backend that needs no sandbox. That covers the contract (tools
discovered, arguments validated, conversion actually performed) without a
container. LibreOffice has to be on PATH; without it the conversion case is
skipped and the rest still runs.

PYTHONPATH is set here for the same reason the runner sets it: the server calls
`environments.attach()` and so has to import the package, from a `uv run` that
does not inherit this interpreter.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())


async def main() -> None:
    workdir = Path(tempfile.mkdtemp())
    (workdir / "note.txt").write_text("중간보고서 초안\n에이전트향 LLM\n", encoding="utf-8")

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

        result = await session.call_tool("list_supported_formats", {})
        assert "pdf" in result.content[0].text, result.content[0].text
        print("list_supported_formats -> ok")

        # An unknown format must be refused before anything is launched, and
        # the message has to name what is accepted: the agent recovers from
        # the error text alone.
        bad = await session.call_tool("convert_document", {"path": "note.txt", "to_format": "zzz"})
        assert bad.is_error and "pdf" in bad.content[0].text, bad.content[0].text
        print("unknown format -> refused, and says what is supported")

        missing = await session.call_tool(
            "convert_document", {"path": "absent.txt", "to_format": "pdf"}
        )
        assert missing.is_error and "No such file" in missing.content[0].text
        print("missing file -> refused")

        if shutil.which("soffice") is None:
            print("soffice not on PATH — conversion case skipped")
        else:
            out = await session.call_tool(
                "convert_document", {"path": "note.txt", "to_format": "pdf"}
            )
            assert not out.is_error, out.content[0].text
            print(f"convert_document -> {out.content[0].text}")

            text = await session.call_tool("extract_text", {"path": "note.txt"})
            assert "중간보고서" in text.content[0].text, text.content[0].text
            print("extract_text -> Korean survived the round trip")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
