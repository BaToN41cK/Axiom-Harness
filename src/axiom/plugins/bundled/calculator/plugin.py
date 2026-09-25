"""AXIOM built-in plugin: safe arithmetic calculator (AST-based, no eval)."""

from __future__ import annotations

import ast
import math

from axiom.core.tools.base import ToolDefinition, ToolPermission, ToolResult

MAX_EXPRESSION_LEN = 200

_FUNCTIONS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "floor": math.floor, "ceil": math.ceil, "pow": pow, "exp": math.exp,
}

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        operations = {
            ast.Add: lambda: left + right,
            ast.Sub: lambda: left - right,
            ast.Mult: lambda: left * right,
            ast.Div: lambda: left / right,
            ast.FloorDiv: lambda: left // right,
            ast.Mod: lambda: left % right,
            ast.Pow: lambda: left ** right,
        }
        operation = next((fn for op, fn in operations.items() if isinstance(node.op, op)), None)
        if operation is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return operation()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in _FUNCTIONS:
            raise ValueError(f"unknown function: {node.func.id}")
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        arguments = [_evaluate(argument) for argument in node.args]
        return _FUNCTIONS[node.func.id](*arguments)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


TOOLS = [
    ToolDefinition(
        name="calculate",
        description=(
            "Evaluate a safe arithmetic expression. Supports + - * / // % **, "
            "parentheses, functions sqrt/sin/cos/tan/log/log2/log10/floor/ceil/"
            "abs/round/min/max/pow/exp and constants pi, e, tau. "
            "Only numeric math is allowed — no variable access, no eval."
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic expression to evaluate, e.g. '2 + 3 * sqrt(16)'.",
                },
            },
            "required": ["expression"],
        },
        permission=ToolPermission.ALWAYS,
        max_output=1000,
    ),
]


async def calculate(expression: str) -> ToolResult:
    try:
        if not expression or not expression.strip():
            return ToolResult(name="calculate", ok=False, error="expression is required")
        if len(expression) > MAX_EXPRESSION_LEN:
            return ToolResult(
                name="calculate",
                ok=False,
                error=f"expression is too long (max {MAX_EXPRESSION_LEN} chars)",
            )
        tree = ast.parse(expression.strip(), mode="eval")
        value = _evaluate(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return ToolResult(name="calculate", ok=False, error=str(exc))
    rounded = round(value, 12)
    rendered = str(int(rounded)) if isinstance(rounded, float) and rounded.is_integer() else str(rounded)
    return ToolResult(name="calculate", ok=True, content=f"{expression.strip()} = {rendered}")


HANDLERS = {"calculate": calculate}
