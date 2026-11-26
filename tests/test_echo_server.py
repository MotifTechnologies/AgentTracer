"""Behaviour tests for the bundled echo server, called directly."""

import importlib.util
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1] / "src/agent_tracer/mcp_servers/echo/server.py"
)


@pytest.fixture(scope="module")
def echo_server():
    spec = importlib.util.spec_from_file_location("echo_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_echo_returns_the_text(echo_server):
    assert echo_server.echo("hello") == "hello"


def test_repeat_joins_copies_with_spaces(echo_server):
    assert echo_server.echo("hi", repeat=3) == "hi hi hi"


@pytest.mark.parametrize("repeat", [0, 11, -1])
def test_repeat_outside_1_to_10_is_refused(echo_server, repeat):
    with pytest.raises(ValueError, match="between 1 and 10"):
        echo_server.echo("hi", repeat=repeat)
