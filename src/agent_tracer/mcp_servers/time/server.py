# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""The current time, and converting between zones.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

No sandbox: a clock is the same everywhere, so this ignores the sandbox
environment entirely.

A model has no clock. Asked what time it is somewhere, it answers from whatever
date appeared in its context, and asked to convert between zones it applies a
remembered offset — which is right until a DST boundary, a zone that changed its
rules, or a half-hour offset like Kolkata's. Those are exactly the cases a task
is likely to be testing, and the ones the model gets wrong with most confidence.

Zone data comes from the system. This server runs on the runner's host rather
than in a task image, so that is a normal OS with /usr/share/zoneinfo; and where
it is missing, `ZoneInfo` raises instead of guessing an offset, which the unknown
timezone path turns into a message naming the fix. A host without zone data can
add `tzdata` to this script's dependencies.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from mcp.server import MCPServer

mcp = MCPServer(name="time", version="0.1.0")


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unknown timezone {name!r}. Use an IANA name such as 'Asia/Seoul' "
            "or 'America/New_York'; list_timezones searches them."
        ) from exc


def _offset(moment: datetime) -> str:
    """The moment's offset from UTC, as +HH:MM."""
    offset = moment.utcoffset()
    total_minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if total_minutes >= 0 else "-"
    return f"{sign}{abs(total_minutes) // 60:02d}:{abs(total_minutes) % 60:02d}"


def _describe(moment: datetime) -> dict:
    return {
        "timezone": str(moment.tzinfo),
        "datetime": moment.isoformat(),
        "date": moment.date().isoformat(),
        "time": moment.time().isoformat(timespec="seconds"),
        "weekday": moment.strftime("%A"),
        # Named separately because a model asked to "show the offset" otherwise
        # reads it off the ISO string, and gets the sign wrong about as often
        # as not.
        "utc_offset": _offset(moment),
        "is_dst": bool(moment.dst()),
    }


def _reject_unreal(naive: datetime, zone: ZoneInfo, zone_name: str, given: str) -> None:
    """Refuse a wall clock that never happens, or that happens twice.

    `replace(tzinfo=...)` takes any local time at face value and reads it with
    fold=0. On the two days a year a zone shifts, that is either an answer to a
    question with none, or one of two equally correct answers given as if it
    were the only one — and a DST boundary is exactly what a task asking this
    server anything is likely to be testing.
    """
    earlier = naive.replace(tzinfo=zone, fold=0)
    later = naive.replace(tzinfo=zone, fold=1)

    # A skipped wall clock does not survive a round trip through UTC: the
    # instant it maps to reads back as a different local time.
    if earlier.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError(
            f"{given!r} does not exist in {zone_name} — the clock skips that hour when "
            "daylight saving starts. Pick a time outside the gap, or give it in UTC."
        )
    if earlier.utcoffset() != later.utcoffset():
        raise ValueError(
            f"{given!r} happens twice in {zone_name} — once at {_offset(earlier)} and "
            f"again at {_offset(later)}, when daylight saving ends. Say which one by "
            "giving the time in UTC."
        )


@mcp.tool()
def current_time(timezone: str = "UTC") -> dict:
    """The time right now in a timezone.

    Args:
        timezone: IANA timezone name, e.g. "Asia/Seoul", "UTC".
    """
    return _describe(datetime.now(_zone(timezone)))


@mcp.tool()
def convert_time(datetime_str: str, from_timezone: str, to_timezone: str) -> dict:
    """Convert a wall-clock time from one timezone to another.

    A local time that a daylight-saving change skips, or that it repeats, is
    refused rather than answered: the first has no reading and the second has
    two. Give such a time in UTC instead.

    Args:
        datetime_str: The time to convert, ISO 8601, e.g. "2026-08-06T14:30" or
            "2026-08-06 14:30:00". Any offset in the string is ignored in
            favour of `from_timezone`.
        from_timezone: IANA timezone the time is given in.
        to_timezone: IANA timezone to convert it to.
    """
    source, target = _zone(from_timezone), _zone(to_timezone)
    try:
        naive = datetime.fromisoformat(datetime_str.strip())
    except ValueError as exc:
        raise ValueError(
            f"Could not read {datetime_str!r} as a date and time. "
            "Use ISO 8601, e.g. '2026-08-06T14:30'."
        ) from exc

    _reject_unreal(naive, source, from_timezone, datetime_str)
    origin = naive.replace(tzinfo=source)
    converted = origin.astimezone(target)
    return {
        "from": _describe(origin),
        "to": _describe(converted),
        # The part a model is most likely to state wrongly in prose.
        "day_offset": (converted.date() - origin.date()).days,
    }


@mcp.tool()
def list_timezones(search: str | None = None, max_results: int = 50) -> dict:
    """List IANA timezone names, optionally filtered.

    Args:
        search: Case-insensitive substring, e.g. "seoul" or "america/new".
        max_results: Stop after this many names.
    """
    if max_results < 1:
        raise ValueError("max_results must be >= 1")

    names = sorted(available_timezones())
    if search:
        needle = search.strip().lower()
        names = [n for n in names if needle in n.lower()]

    window = names[:max_results]
    return {"timezones": window, "count": len(window), "total_matches": len(names)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
