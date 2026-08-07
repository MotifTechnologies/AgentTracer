# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: connect to the context7 endpoint (as the runner would).

    cd src/agent_tracer/mcp_servers/context7 && uv run smoke_test.py

Unlike the other servers here, nothing is spawned — the manifest names a hosted
Streamable HTTP endpoint whose lifecycle is somebody else's. So this test needs
outbound network, and a failure means either the network or Context7, not this
repository. It says which.

What it checks is the part we depend on and do not control: that the two tools
are still named what the manifest says, that resolve → query composes, and that
a query comes back with something a model could act on.
"""

import asyncio
import json
import os
import re
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())

# The runner resolves `env:` refs before connecting; here the header is only
# sent if the variable happens to be set, since the endpoint is usable without.
HEADERS = {
    k: os.environ[v[4:]]
    for k, v in MANIFEST.get("headers", {}).items()
    if not v.startswith("env:") or v[4:] in os.environ
}


async def main() -> None:
    url = MANIFEST["url"]
    print(f"connecting: {url}")
    try:
        http_client = create_mcp_http_client(headers=HEADERS) if HEADERS else None
        async with (
            streamable_http_client(url, http_client=http_client) as (read, write),
            ClientSession(read, write) as session,
        ):
            init = await session.initialize()
            print(f"server: {init.server_info.name} {init.server_info.version}")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"discovered tools: {names}")
            declared = [t["name"] for t in MANIFEST.get("tools", [])]
            assert set(declared) <= set(names), (
                f"manifest declares {declared}, endpoint exposes {names} — "
                "the hosted server changed its tool names"
            )

            res = await session.call_tool(
                "resolve-library-id", {"query": "extract text from a PDF", "libraryName": "pypdf"}
            )
            assert not res.is_error, res.content[0].text[:300]
            listing = res.content[0].text
            assert "pypdf" in listing.lower(), listing[:300]
            print("resolve-library-id -> ok")

            # The whole point of the two-step: the id from the first call is
            # what the second one takes. If that shape changes, a model
            # following the tool descriptions breaks.
            match = re.search(r"^- Context7-compatible library ID: (\S+)", listing, re.MULTILINE)
            assert match, f"no library ID in the listing:\n{listing[:400]}"
            library_id = match.group(1)
            print(f"  resolved id: {library_id}")

            res = await session.call_tool(
                "query-docs", {"libraryId": library_id, "query": "extract text from a page"}
            )
            assert not res.is_error, res.content[0].text[:300]
            docs = res.content[0].text
            assert len(docs) > 200, f"suspiciously short answer: {docs!r}"
            print(f"query-docs -> ok, {len(docs)} chars")
            print("  " + docs.strip().splitlines()[0][:100])

    except AssertionError:
        raise
    except Exception as exc:
        raise SystemExit(
            f"could not reach {url}: {type(exc).__name__}: {exc}\n"
            "This server is a hosted endpoint — check outbound network and "
            "https://context7.com before looking at this repository."
        ) from exc

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
