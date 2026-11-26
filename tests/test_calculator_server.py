"""Behaviour tests for the bundled calculator server, called directly."""

import importlib.util
from pathlib import Path

import pytest

SERVER = (
    Path(__file__).resolve().parents[1]
    / "src/agent_tracer/mcp_servers/calculator/server.py"
)


@pytest.fixture(scope="module")
def calculator():
    spec = importlib.util.spec_from_file_location("calculator_server", SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_precedence(calculator):
    assert calculator.calculate("2 + 3 * 4")["result"] == "14"
    assert calculator.calculate("(2 + 3) * 4")["result"] == "20"


def test_decimal_arithmetic_is_exact(calculator):
    # 0.1 + 0.2 must read as 0.3, not the float behind it.
    result = calculator.calculate("0.1 + 0.2")
    assert result["result"] == "0.3"
    assert result["exact"] is True


def test_floor_division_and_modulo_follow_python(calculator):
    # Decimal truncates toward zero; the server promised Python semantics.
    assert calculator.calculate("-7 // 2")["result"] == "-4"
    assert calculator.calculate("-7 % 2")["result"] == "1"


def test_non_terminating_division_is_marked_inexact(calculator):
    result = calculator.calculate("1 / 3")
    assert result["exact"] is False
    assert result["result"].startswith("0.333")


def test_division_by_zero_is_refused(calculator):
    with pytest.raises(ValueError, match="Division by zero"):
        calculator.calculate("1 / 0")


@pytest.mark.parametrize(
    "expression",
    [
        "x + 1",  # a name
        "math.pi",  # attribute access
        "abs(-1)",  # a function call
        "'42'",  # a string
        "True",  # a boolean
    ],
)
def test_anything_but_arithmetic_is_refused(calculator, expression):
    with pytest.raises(ValueError):
        calculator.calculate(expression)


def test_a_huge_exponent_is_refused(calculator):
    with pytest.raises(ValueError, match="exponent"):
        calculator.calculate("2 ** 1001")


def test_unparseable_input_is_refused(calculator):
    with pytest.raises(ValueError, match="Could not parse"):
        calculator.calculate("2 +")
