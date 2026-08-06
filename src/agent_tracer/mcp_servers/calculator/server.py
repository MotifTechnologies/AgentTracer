# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0,<3"]
# ///
"""Arithmetic, without handing the model a shell.

Launched by the runner as declared in mcp.json:
    uv run --quiet server.py    (stdio transport)

An agent that needs a sum has `code_exec` and will reach for it, which puts
`python3 -c "print(...)"` in the trajectory where an arithmetic step belongs.
That is a worse training example than the same step recorded as
`calculate(expression="1.1 + 2.2")`, and it costs a container round trip.

Evaluated by walking the parsed AST, not `eval`. `eval` on model output is the
kind of thing that is fine until a task description contains something that
isn't arithmetic, and the sandbox is not the boundary here — this server runs
outside it.

Decimal, not float: an agent checking a number against a rubric should not be
told 0.1 + 0.2 is 0.30000000000000004.
"""

import ast
import operator
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext

from mcp.server import MCPServer

mcp = MCPServer(name="calculator", version="0.1.0")

getcontext().prec = 50

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

#: Guards `**`. Decimal will happily try 9**9**9 and take the process with it.
MAX_EXPONENT = 1000


def _eval(node: ast.AST) -> Decimal:
    match node:
        case ast.Expression():
            return _eval(node.body)
        case ast.Constant(value=bool()):
            raise ValueError("booleans are not numbers here")
        case ast.Constant(value=int() | float() | str() as value):
            return Decimal(str(value))
        case ast.UnaryOp(op=op) if type(op) in _UNARY:
            return _UNARY[type(op)](_eval(node.operand))
        case ast.BinOp(op=op) if type(op) in _BINARY:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError(f"exponent larger than {MAX_EXPONENT} refused")
            return _BINARY[type(op)](left, right)
        case _:
            raise ValueError(
                f"{type(node).__name__} is not allowed — this evaluates arithmetic only, "
                "not names, calls or comparisons"
            )


@mcp.tool()
def calculate(expression: str) -> dict:
    """Evaluate an arithmetic expression exactly.

    Supports + - * / // % ** and parentheses over decimal numbers. Names,
    function calls and anything else are refused.

    Args:
        expression: The expression to evaluate, e.g. "(1.1 + 2.2) * 3".
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Could not parse {expression!r}: {exc.msg}") from exc

    try:
        result = _eval(tree)
    except (DivisionByZero, ZeroDivisionError) as exc:
        raise ValueError("Division by zero") from exc
    except InvalidOperation as exc:
        raise ValueError(f"Undefined result for {expression!r}") from exc

    # Normalised so 2.50 and 2.5 do not read as different answers, and without
    # exponent notation, which a rubric comparing strings would not match.
    normalised = result.normalize()
    text = format(normalised, "f")
    return {"expression": expression, "result": text}


if __name__ == "__main__":
    mcp.run(transport="stdio")
