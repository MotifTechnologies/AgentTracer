# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Smoke test: spawn the time server over stdio (as the runner would).

    cd src/agent_tracer/mcp_servers/time && uv run smoke_test.py

No sandbox is involved, so no PYTHONPATH either — this server never imports the
package. Zone data comes from the system; the assertions below fail loudly if a
host has none rather than passing vacuously.

The cases worth asserting are the ones a model gets wrong from memory: a
half-hour offset, a DST boundary, and a conversion that crosses midnight.
"""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
MANIFEST = json.loads((HERE / "mcp.json").read_text())


def _payload(result):
    return json.loads(result.content[0].text)


async def main() -> None:
    params = StdioServerParameters(
        command=MANIFEST["command"], args=MANIFEST["args"], cwd=str(HERE)
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print(f"discovered tools: {names}")
        declared = [t["name"] for t in MANIFEST.get("tools", [])]
        assert set(declared) <= set(names), f"manifest declares {declared}, server exposes {names}"

        out = _payload(await session.call_tool("current_time", {"timezone": "Asia/Seoul"}))
        assert out["utc_offset"] == "+09:00" and not out["is_dst"], out
        print(f"current_time Asia/Seoul -> {out['datetime']} ({out['weekday']})")

        out = _payload(await session.call_tool("current_time", {}))
        assert out["timezone"] == "UTC" and out["utc_offset"] == "+00:00", out
        print("current_time default UTC -> ok")

        # Kolkata is +05:30. A model applying a remembered whole-hour offset
        # lands 30 minutes out, and states it confidently.
        out = _payload(await session.call_tool("convert_time", {
            "datetime_str": "2026-08-06T14:00", "from_timezone": "UTC", "to_timezone": "Asia/Kolkata"}))
        assert out["to"]["time"] == "19:30:00" and out["to"]["utc_offset"] == "+05:30", out
        print("convert_time half-hour offset -> ok")

        # New York in August is EDT (-04:00), not EST (-05:00). The rule is
        # seasonal, so a remembered offset is right only half the year.
        out = _payload(await session.call_tool("convert_time", {
            "datetime_str": "2026-08-06T12:00", "from_timezone": "America/New_York", "to_timezone": "UTC"}))
        assert out["from"]["utc_offset"] == "-04:00" and out["from"]["is_dst"], out
        assert out["to"]["time"] == "16:00:00", out
        print("convert_time DST-aware -> ok, EDT not EST")

        # And in January the same zone is -05:00.
        out = _payload(await session.call_tool("convert_time", {
            "datetime_str": "2026-01-06T12:00", "from_timezone": "America/New_York", "to_timezone": "UTC"}))
        assert out["from"]["utc_offset"] == "-05:00" and not out["from"]["is_dst"], out
        print("convert_time winter -> ok, EST")

        # Crossing midnight: the date changes, and day_offset says so rather
        # than leaving it to be inferred from two ISO strings.
        # Seoul is nine hours ahead, so an early morning there is the previous
        # day in UTC.
        out = _payload(await session.call_tool("convert_time", {
            "datetime_str": "2026-08-06T05:00", "from_timezone": "Asia/Seoul", "to_timezone": "UTC"}))
        assert out["to"]["date"] == "2026-08-05" and out["to"]["time"] == "20:00:00", out
        assert out["day_offset"] == -1, out
        print(f"convert_time across midnight -> day_offset={out['day_offset']}")

        # And the other way, which must not be reported as -1.
        out = _payload(await session.call_tool("convert_time", {
            "datetime_str": "2026-08-06T20:00", "from_timezone": "UTC", "to_timezone": "Asia/Seoul"}))
        assert out["to"]["date"] == "2026-08-07" and out["day_offset"] == 1, out
        print("convert_time forward across midnight -> day_offset=+1")

        out = _payload(await session.call_tool("list_timezones", {"search": "seoul"}))
        assert out["timezones"] == ["Asia/Seoul"], out
        print("list_timezones search -> ok")

        out = _payload(await session.call_tool("list_timezones", {"max_results": 5}))
        assert out["count"] == 5 and out["total_matches"] > 100, out
        print("list_timezones cap -> ok, total reported separately")

        bad = await session.call_tool("current_time", {"timezone": "Mars/Olympus"})
        assert bad.is_error and "Asia/Seoul" in bad.content[0].text, bad.content[0].text
        print("unknown timezone -> refused, and shows the expected form")

        bad = await session.call_tool("convert_time", {
            "datetime_str": "next tuesday", "from_timezone": "UTC", "to_timezone": "UTC"})
        assert bad.is_error and "ISO 8601" in bad.content[0].text, bad.content[0].text
        print("unparseable time -> refused, and says what it wants")

    print("smoke test OK")


if __name__ == "__main__":
    asyncio.run(main())
