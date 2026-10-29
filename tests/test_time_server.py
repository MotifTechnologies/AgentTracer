"""The bundled time server's conversion, called directly rather than over stdio."""

import importlib.util
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1] / "src/agent_tracer/mcp_servers/time/server.py"
)


@pytest.fixture(scope="module")
def time_server():
    spec = importlib.util.spec_from_file_location("time_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "given", ["2026-08-06T14:30", "2026-08-06T14:30:00Z", "2026-08-06T14:30+09:00"]
)
def test_offset_in_the_string_is_ignored(time_server, given):
    result = time_server.convert_time(given, "Asia/Seoul", "UTC")
    assert (
        result["to"]
        == time_server.convert_time("2026-08-06T14:30", "Asia/Seoul", "UTC")["to"]
    )
    assert result["to"]["datetime"] == "2026-08-06T05:30:00+00:00"


def test_skipped_hour_is_still_refused(time_server):
    # 02:30 does not exist in New York on the 2026 spring-forward date.
    with pytest.raises(ValueError, match="does not exist"):
        time_server.convert_time("2026-03-08T02:30Z", "America/New_York", "UTC")
