"""Model expressions: parse with SymPy against a whitelist, lambdify to NumPy.

Every bare name in an expression is either a whitelisted function/constant, the
independent variable, or a parameter. Calling anything that is not whitelisted
is an error that names it.

This is input validation, not a sandbox: like all SFS node code, model code
runs with the backend's privileges.
"""
from __future__ import annotations

import io
import keyword
import tokenize
from dataclasses import dataclass
from typing import Callable

FUNCTIONS = ("exp", "log", "sqrt", "sin", "cos", "tan", "sinh", "cosh", "tanh", "abs")
CONSTANTS = ("pi", "e")


class ExpressionError(ValueError):
    pass


@dataclass
class ParsedModel:
    expression: str            # as written (normalised: ^ → **)
    variable: str
    params: list[str]          # in order of first appearance
    sympy_expr: object
    func: Callable             # func(variable, *params) → numpy array


def _names(text: str) -> list[tuple[str, bool]]:
    """(name, is_called) for every identifier token, in order."""
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                if t.type not in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER)]
    except (tokenize.TokenError, IndentationError) as exc:
        raise ExpressionError(f"Could not read the expression: {exc}") from None
    out = []
    for i, t in enumerate(toks):
        if t.type == tokenize.NAME:
            called = i + 1 < len(toks) and toks[i + 1].string == "("
            out.append((t.string, called))
    return out


def parse(expression: str, variable: str = "x") -> ParsedModel:
    import sympy as sp
    from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

    text = (expression or "").strip()
    variable = (variable or "x").strip()
    if not text:
        raise ExpressionError("The model expression is empty")
    if not variable.isidentifier() or keyword.iskeyword(variable):
        raise ExpressionError(f"'{variable}' is not a valid variable name")

    functions = {"exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos,
                 "tan": sp.tan, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "abs": sp.Abs}
    constants = {"pi": sp.pi, "e": sp.E}

    local: dict = {}
    params: list[str] = []
    unknown_calls: list[str] = []
    for name, called in _names(text):
        if keyword.iskeyword(name):
            raise ExpressionError(f"'{name}' is a Python keyword and can't be a name in a model; rename it")
        if called:
            if name in functions:
                local[name] = functions[name]
            elif name not in unknown_calls:
                unknown_calls.append(name)
            continue
        if name in constants:
            local[name] = constants[name]
        elif name in functions:
            raise ExpressionError(f"'{name}' is a function; call it, e.g. {name}(x)")
        else:
            local[name] = sp.Symbol(name, real=True)
            if name != variable and name not in params:
                params.append(name)
    if unknown_calls:
        raise ExpressionError(
            f"Unknown function{'s' if len(unknown_calls) > 1 else ''}: {', '.join(unknown_calls)}. "
            f"Allowed: {', '.join(FUNCTIONS)}; constants: {', '.join(CONSTANTS)}")
    if variable not in local:
        raise ExpressionError(f"The expression doesn't use the variable '{variable}'")
    if not params:
        raise ExpressionError("The expression has no parameters to fit")

    # Only number/symbol constructors are reachable; every name was mapped above.
    safe_globals = {"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
                    "Symbol": sp.Symbol, "__builtins__": {}}
    try:
        sym = parse_expr(text, local_dict=local, global_dict=safe_globals,
                         transformations=standard_transformations + (convert_xor,))
    except Exception as exc:  # SyntaxError, TypeError from bad arity, …
        raise ExpressionError(f"Could not parse the expression: {exc}") from None

    args = [local[variable]] + [local[p] for p in params]
    func = sp.lambdify(args, sym, modules="numpy")
    return ParsedModel(expression=text.replace("^", "**"), variable=variable,
                       params=params, sympy_expr=sym, func=func)


def parse_assignments(text: str, what: str = "initial guesses") -> dict[str, float]:
    """'A=1, tau=2.5' → {'A': 1.0, 'tau': 2.5}."""
    out: dict[str, float] = {}
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ExpressionError(f"Write {what} as name=value, e.g. A=1, tau=2 (got '{part}')")
        name, value = (s.strip() for s in part.split("=", 1))
        try:
            out[name] = float(value)
        except ValueError:
            raise ExpressionError(f"{what.capitalize()}: '{value}' is not a number (for {name})") from None
    return out
