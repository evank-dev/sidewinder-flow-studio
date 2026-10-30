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
# Module names the model's Python source refers to; a parameter can't shadow them.
RESERVED = ("np", "unp", "uabs")


class ExpressionError(ValueError):
    pass


@dataclass
class ParsedModel:
    expression: str            # as written (normalised: ^ → **)
    variable: str
    params: list[str]          # in order of first appearance
    sympy_expr: object
    func: Callable             # func(*args) → numpy array
    args: list[str]            # the variable (if used), then the parameters
    np_body: str               # the expression in NumPy:          A*np.exp(-t/tau)
    unp_body: str              # … and with uncertainties' unumpy: A*unp.exp(-t/tau)

    def source(self, body: str | None = None, name: str = "model") -> str:
        """The model as a Python function. View as Python shows exactly this
        text, and the engine runs it, so both always compute the same thing."""
        return f"def {name}({', '.join(self.args)}):\n    return {body or self.np_body}\n"

    def uncertain_func(self) -> Callable:
        """The model over uncertainties' arrays (first-order error propagation)."""
        return _compile(self.source(self.unp_body), self.args)


def uabs(u):
    """abs() for uncertainties arrays (their own abs is deprecated)."""
    import numpy as np
    from uncertainties import unumpy as unp
    return np.where(unp.nominal_values(u) < 0, -u, u)


def _compile(source: str, args: list[str]) -> Callable:
    import numpy as np
    from uncertainties import unumpy as unp

    scope = {"np": np, "unp": unp, "uabs": uabs, "__builtins__": {}}
    exec(source, scope)  # noqa: S102 — source built from validated tokens only
    return scope["model"]


def _rewrite(text: str, module: str) -> str:
    """The expression as Python: whitelisted functions and constants prefixed
    with their module, ^ as **. Everything else is kept as written."""
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    out, pos = [], 0
    for i, t in enumerate(toks):
        if t.type == tokenize.ENDMARKER:
            break
        start, end = t.start[1], t.end[1]
        new = t.string
        if t.type == tokenize.NAME:
            called = i + 1 < len(toks) and toks[i + 1].string == "("
            if called and t.string in FUNCTIONS:
                new = "uabs" if (module == "unp" and t.string == "abs") else f"{module}.{t.string}"
            elif not called and t.string in CONSTANTS:
                new = f"np.{t.string}"
        elif t.type == tokenize.OP and t.string == "^":
            new = "**"
        out.append(text[pos:start] + new)
        pos = end
    return ("".join(out) + text[pos:]).strip()


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


def parse(expression: str, variable: str = "x", *, strict: bool = True) -> ParsedModel:
    """Parse a model. `strict` (fitting) requires the variable and at least one
    parameter; Evaluate also accepts plain formulas such as m*g*h."""
    import sympy as sp
    from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

    text = " ".join((expression or "").split())     # one line
    variable = (variable or "x").strip()
    if not text:
        raise ExpressionError("The model expression is empty")
    if not variable.isidentifier() or keyword.iskeyword(variable):
        raise ExpressionError(f"'{variable}' is not a valid variable name")
    if variable in RESERVED:
        raise ExpressionError(f"'{variable}' is reserved; use another variable name")

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
            if name in RESERVED:
                raise ExpressionError(f"'{name}' is reserved; rename that parameter")
            local[name] = sp.Symbol(name, real=True)
            if name != variable and name not in params:
                params.append(name)
    if unknown_calls:
        raise ExpressionError(
            f"Unknown function{'s' if len(unknown_calls) > 1 else ''}: {', '.join(unknown_calls)}. "
            f"Allowed: {', '.join(FUNCTIONS)}; constants: {', '.join(CONSTANTS)}")
    if strict and variable not in local:
        raise ExpressionError(f"The expression doesn't use the variable '{variable}'")
    if strict and not params:
        raise ExpressionError("The expression has no parameters to fit")

    # Only number/symbol constructors are reachable; every name was mapped above.
    safe_globals = {"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
                    "Symbol": sp.Symbol, "__builtins__": {}}
    try:
        sym = parse_expr(text, local_dict=local, global_dict=safe_globals,
                         transformations=standard_transformations + (convert_xor,))
    except Exception as exc:  # SyntaxError, TypeError from bad arity, …
        raise ExpressionError(f"Could not parse the expression: {exc}") from None

    args = ([variable] if variable in local else []) + params
    np_body = _rewrite(text, "np")
    pm = ParsedModel(expression=text.replace("^", "**"), variable=variable, params=params,
                     sympy_expr=sym, func=None, args=args, np_body=np_body,
                     unp_body=_rewrite(text, "unp"))
    pm.func = _compile(pm.source(), args)
    return pm


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
