"""Evaluating a model: parameters → values.

Two modes:
    range    — the model over an even grid of the variable: `<variable>, value`
    columns  — the model over the upstream rows. The variable is read from the
               x column (the field, else the fit's x column, else the column
               named like the variable); every other name in the expression
               that is not a parameter is read from the column of that name;
               `<name>_err` columns are propagated with `uncertainties`
               (first order) into `<output>_err`.

Parameters come from an upstream parameter table (Curve fit's output) when one
is connected, else from the `parameters` string. The table is recognised by its
columns, never by input position: SFS orders inputs by parent node id, which
the user can't control.

Parameter uncertainties are not propagated: doing that correctly needs the
parameter covariance matrix, which the table does not carry (v1 limitation).
"""
from __future__ import annotations

from . import presets
from .expr import ExpressionError, parse, parse_assignments

TABLE_SIGNATURE = ("kind", "name", "value", "stderr")
FROM_FIT = "from_fit"


class EvalError(ValueError):
    pass


def is_parameter_table(df) -> bool:
    return df is not None and set(TABLE_SIGNATURE) <= set(map(str, df.columns))


def split_inputs(frames):
    """(parameter table or None, data frames) from all upstream frames."""
    frames = [f for f in frames if f is not None and len(f.columns) > 0]
    tables = [f for f in frames if is_parameter_table(f)]
    if len(tables) > 1:
        raise EvalError("More than one parameter table is connected; connect one Curve fit node")
    data = [f for f in frames if not is_parameter_table(f)]
    return (tables[0] if tables else None), data


def _table_model(table) -> dict[str, str]:
    rows = table[table["kind"] == "model"]
    if "text" not in table.columns:
        return {}
    return {str(n): str(t) for n, t in zip(rows["name"], rows["text"]) if isinstance(t, str) and t}


def _table_params(table) -> dict[str, float]:
    rows = table[table["kind"] == "parameter"]
    return {str(n): float(v) for n, v in zip(rows["name"], rows["value"])}


def resolve(table, *, model: str = FROM_FIT, expression: str = "", variable: str = "x",
            parameters: str = ""):
    """(ParsedModel or None, parameter values, preset, fit's x column) from the
    table and/or the form. The model is None for presets lmfit must evaluate
    (Voigt).

    An explicit Model choice overrides the table's model; with "From the
    connected fit" the table's model rows are used.
    """
    model = (model or "").strip() or FROM_FIT
    preset = None
    info = _table_model(table) if table is not None else {}
    if model == FROM_FIT:
        if table is None:
            raise EvalError("No fit is connected: connect a Curve fit node, or pick a Model "
                            "and enter its parameters")
        if not info.get("expression"):
            raise EvalError("The connected parameter table has no model row (expression)")
        expression, variable = info["expression"], info.get("variable") or "x"
        preset = info.get("preset") or presets.CUSTOM
    elif model == presets.CUSTOM:
        preset = presets.CUSTOM
    else:
        p = presets.BY_ID.get(model)
        if p is None:
            raise EvalError(f"Unknown model '{model}'. Pick one from the list, or 'custom'.")
        expression, variable, preset = p["expression"], p["variable"], p["id"]

    if table is not None:
        values = _table_params(table)
        if (parameters or "").strip():
            print("Note: a parameter table is connected, so the Parameters field is ignored")
    else:
        try:
            values = parse_assignments(parameters, "parameters")
        except ExpressionError as exc:
            raise EvalError(str(exc)) from None

    p = presets.BY_ID.get(preset or "", {})
    x_column = info.get("x_column") or ""
    if p.get("evaluable") is False:
        return None, values, p, x_column
    try:
        pm = parse(expression, variable or "x", strict=False)
    except ExpressionError as exc:
        raise EvalError(str(exc)) from None
    return pm, values, p, x_column


def _lmfit_eval(preset: dict, values: dict, xs):
    """Presets with no closed form in the whitelist (Voigt): lmfit evaluates."""
    import lmfit

    cls_name, kwargs = preset["lmfit"]
    m = getattr(lmfit.models, cls_name)(**kwargs)
    names = list(m.param_names) + list(preset.get("free") or ())
    missing = [n for n in names if n not in values]
    if missing:
        raise EvalError(f"Missing parameter value{'s' if len(missing) > 1 else ''}: {', '.join(missing)}")
    params = m.make_params(**{n: values[n] for n in names})
    for name in preset.get("free") or ():
        params[name].set(value=values[name], expr="")
    return m.eval(params, x=xs)


def _uncertain_modules():
    import numpy as np
    from uncertainties import unumpy as unp

    def uabs(u):
        return np.where(unp.nominal_values(u) < 0, -u, u)

    return [{"exp": unp.exp, "log": unp.log, "sqrt": unp.sqrt, "sin": unp.sin, "cos": unp.cos,
             "tan": unp.tan, "sinh": unp.sinh, "cosh": unp.cosh, "tanh": unp.tanh,
             "abs": uabs, "Abs": uabs}, "numpy"]


def evaluate_range(table=None, *, model=FROM_FIT, expression="", variable="x", parameters="",
                   start=None, stop=None, points=200):
    """The model over an even grid. The grid column is named after the fit's x
    column when a fit is connected (so curve and data share an axis), else
    after the variable."""
    import numpy as np
    import pandas as pd

    pm, values, preset, x_column = resolve(table, model=model, expression=expression,
                                           variable=variable, parameters=parameters)
    if start in (None, "") or stop in (None, ""):
        raise EvalError("Range mode needs Start and Stop")
    try:
        n = int(points or 200)
    except (TypeError, ValueError):
        raise EvalError("Points must be a whole number") from None
    if n < 2:
        raise EvalError("Points must be at least 2")
    xs = np.linspace(float(start), float(stop), n)
    var = pm.variable if pm is not None else (preset.get("variable") or "x")
    if pm is None:
        ys = _lmfit_eval(preset, values, xs)
    else:
        missing = [p for p in pm.params if p not in values]
        if missing:
            raise EvalError(f"Missing parameter value{'s' if len(missing) > 1 else ''}: "
                            f"{', '.join(missing)} (e.g. Parameters: "
                            f"{', '.join(f'{p}=…' for p in missing)})")
        with np.errstate(all="ignore"):
            ys = np.broadcast_to(pm.func(xs, *[values[p] for p in pm.params]), xs.shape)
    return pd.DataFrame({x_column or var: xs, "value": np.asarray(ys, dtype=float)})


def evaluate_columns(df, table=None, *, model=FROM_FIT, expression="", variable="x",
                     parameters="", output="value", x=""):
    import numpy as np

    if df is None or len(df.columns) == 0:
        raise EvalError("Columns mode needs data: connect the rows to evaluate over "
                        "(or switch Mode to Range)")
    output = (output or "value").strip() or "value"
    pm, values, preset, fit_x = resolve(table, model=model, expression=expression,
                                        variable=variable, parameters=parameters)
    columns = set(map(str, df.columns))
    out = df.copy()
    var = pm.variable if pm is not None else (preset.get("variable") or "x")
    x = (x or "").strip()
    if x and x not in columns:
        raise EvalError(f"Column '{x}' (for the variable {var}) is not in the input. "
                        f"Columns: {', '.join(sorted(columns))}")
    if not x and fit_x in columns:
        x = fit_x
    if x and x != var:
        # Read the variable from column x: rename it (and its _err) to the variable.
        if var in columns:
            print(f"Note: reading {var} from column '{x}', not from the column named '{var}'")
        df = df.drop(columns=[c for c in (var, f"{var}_err") if c in columns])
        df = df.rename(columns={x: var, f"{x}_err": f"{var}_err"})
        columns = set(map(str, df.columns))

    if pm is None:  # Voigt: lmfit evaluates, no propagation through it
        if var not in columns:
            raise EvalError(f"Column '{var}' (the model's variable) is not in the input. "
                            f"Columns: {', '.join(sorted(columns))}")
        if f"{var}_err" in columns:
            raise EvalError(f"Uncertainty propagation isn't available for the {preset['label']} "
                            f"model (no closed form); remove or rename '{var}_err'")
        out[output] = _lmfit_eval(preset, values, df[var].to_numpy(dtype=float))
        return out

    names = [pm.variable] + pm.params
    used = {s.name for s in pm.sympy_expr.free_symbols}
    for name in names:
        if name in values and name in columns and name in used:
            print(f"Note: '{name}' is both a parameter and a column; using the parameter value")
    from_columns = [n for n in names if n not in values and n in used]
    missing = [n for n in from_columns if n not in columns]
    if missing:
        raise EvalError(f"No value for {', '.join(missing)}: not a parameter and not a column. "
                        f"Columns: {', '.join(sorted(columns))}")

    def col(name):
        try:
            return df[name].to_numpy(dtype=float)
        except (TypeError, ValueError):
            raise EvalError(f"Column '{name}' must be numeric") from None

    err_cols = [n for n in from_columns if f"{n}_err" in columns]
    args = {}
    for n in names:
        if n in values:
            args[n] = values[n]
        elif n in from_columns:
            args[n] = col(n)
        else:
            args[n] = 0.0  # the variable, when the expression doesn't use it

    if not err_cols:
        with np.errstate(all="ignore"):
            res = pm.func(*[args[n] for n in names])
        out[output] = np.broadcast_to(np.asarray(res, dtype=float), (len(df),))
        return out

    import sympy as sp
    from uncertainties import unumpy as unp

    for n in err_cols:
        err = col(f"{n}_err")
        if (err[np.isfinite(err)] < 0).any():
            raise EvalError(f"'{n}_err' has negative uncertainties")
        args[n] = unp.uarray(args[n], np.nan_to_num(err, nan=0.0))
    syms = {s.name: s for s in pm.sympy_expr.free_symbols}
    ufunc = sp.lambdify([syms.get(n, sp.Symbol(n, real=True)) for n in names],
                        pm.sympy_expr, modules=_uncertain_modules())
    with np.errstate(all="ignore"):
        res = np.broadcast_to(np.asarray(ufunc(*[args[n] for n in names]), dtype=object), (len(df),))
    out[output] = unp.nominal_values(res).astype(float)
    out[f"{output}_err"] = unp.std_devs(res).astype(float)
    return out
