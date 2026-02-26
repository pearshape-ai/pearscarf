from __future__ import annotations

import ast
import math
import operator
from typing import Any

from pearscaff.tools import BaseTool

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
}

_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](
            _safe_eval(node.left), _safe_eval(node.right)
        )
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
            args = [_safe_eval(a) for a in node.args]
            return float(_FUNCTIONS[node.func.id](*args))
        raise ValueError(f"Unknown function: {ast.dump(node.func)}")
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


class MathTool(BaseTool):
    name = "math"
    description = "Safely evaluate a math expression. Supports +, -, *, /, //, **, %, sqrt, log, log2, log10, sin, cos, tan, abs, round, pi, e."
    input_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The math expression to evaluate, e.g. 'sqrt(144) + 15 * 3'",
            }
        },
        "required": ["expression"],
    }

    def execute(self, **kwargs: Any) -> str:
        expression = kwargs["expression"]
        try:
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree)
            if result == int(result):
                return str(int(result))
            return str(result)
        except Exception as exc:
            return f"Error: {exc}"
