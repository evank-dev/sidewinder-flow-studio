"""Curve fitting: data → parameters with uncertainties, as a tidy table.

Output columns: kind, name, value, stderr, text.
    parameter  — one row per fitted parameter (value ± stderr)
    statistic  — chi2, redchi, r_squared, n_points
    model      — expression, variable, preset, x_column (in `text`)

Arrow needs one type per column, so `value` is always numeric and the model
rows carry their strings in `text`. Downstream nodes find this table by its
columns (TABLE_COLUMNS), never by input position.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import presets
from .expr import ExpressionError, parse, parse_assignments

TABLE_COLUMNS = ("kind", "name", "value", "stderr", "text")


class FitError(ValueError):
    pass


@dataclass
class ModelSpec:
    expression: str
    variable: str
    preset: str              # preset id, or "custom"
    lmfit_model: object      # lmfit.Model ready to fit
    params: list[str]
    linear: bool = False     # linear in its parameters: one exact solution, no local minima


# A nonlinear fit that explains less than this share of the variance has almost
# certainly stopped in a wrong local minimum (lmfit still reports success).
MIN_R_SQUARED_NONLINEAR = 0.1


def _is_linear(pm) -> bool:
    import sympy as sp
    syms = {s.name: s for s in pm.sympy_expr.free_symbols}
    ps = [syms[n] for n in pm.params if n in syms]
    return all(sp.diff(pm.sympy_expr, a, b) == 0 for a in ps for b in ps)


# ── model construction ────────────────────────────────────────────────────────

def build_model(model: str, expression: str = "", variable: str = "x") -> ModelSpec:
    import lmfit

    model = (model or "").strip() or "linear"
    if model == presets.CUSTOM:
        try:
            pm = parse(expression, variable or "x")
        except ExpressionError as exc:
            raise FitError(str(exc)) from None
        m = lmfit.Model(pm.func, independent_vars=[pm.variable], name="custom")
        return ModelSpec(pm.expression, pm.variable, presets.CUSTOM, m, pm.params, _is_linear(pm))

    p = presets.BY_ID.get(model)
    if p is None:
        raise FitError(f"Unknown model '{model}'. Pick one from the list, or 'custom'.")
    if p.get("lmfit"):
        cls_name, kwargs = p["lmfit"]
        m = getattr(lmfit.models, cls_name)(**kwargs)
        names = list(m.param_names) + [n for n in p.get("free") or () if n not in m.param_names]
        return ModelSpec(p["expression"], p["variable"], p["id"], m, names, bool(p.get("linear")))
    pm = parse(p["expression"], p["variable"])
    m = lmfit.Model(pm.func, independent_vars=[pm.variable], name=p["id"])
    return ModelSpec(pm.expression, pm.variable, p["id"], m, pm.params, _is_linear(pm))


# ── starting values ───────────────────────────────────────────────────────────

def _guess_namespace(x, y) -> dict:
    import numpy as np

    def linfit(u, v):
        """(slope, intercept) of a straight line through finite (u, v) points."""
        u, v = np.asarray(u, float), np.asarray(v, float)
        ok = np.isfinite(u) & np.isfinite(v)
        slope, intercept = np.polyfit(u[ok], v[ok], 1)
        return float(slope), float(intercept)

    def x_at(level):
        """x where y is closest to `level`."""
        return float(x[np.argmin(np.abs(y - level))])

    def dominant_freq(xs, ys):
        """Strongest non-zero frequency, after resampling onto an even grid."""
        order = np.argsort(xs)
        xs, ys = np.asarray(xs, float)[order], np.asarray(ys, float)[order]
        n = max(len(xs), 16)
        grid = np.linspace(xs[0], xs[-1], n)
        vals = np.interp(grid, xs, ys) - np.mean(ys)
        spec = np.abs(np.fft.rfft(vals))
        freqs = np.fft.rfftfreq(n, d=grid[1] - grid[0])
        return float(freqs[1:][np.argmax(spec[1:])])

    with np.errstate(all="ignore"):
        return {"x": x, "y": y, "np": np, "max": np.max, "min": np.min, "mean": np.mean,
                "abs": np.abs, "log": np.log, "exp": np.exp, "sqrt": np.sqrt, "ptp": np.ptp,
                "argmin": np.argmin, "argmax": np.argmax, "linfit": linfit, "x_at": x_at,
                "dominant_freq": dominant_freq, "__builtins__": {}}


def _initial_params(spec: ModelSpec, x, y, initial: dict[str, float]):
    """lmfit Parameters: preset/lmfit guesses, then the user's values on top."""
    import math
    import warnings

    import numpy as np

    unknown = sorted(set(initial) - set(spec.params))
    if unknown:
        raise FitError(f"Initial guesses name unknown parameters: {', '.join(unknown)}. "
                       f"This model's parameters: {', '.join(spec.params)}")

    preset = presets.BY_ID.get(spec.preset, {})
    params = None
    guessed: set[str] = set()
    if preset.get("lmfit"):
        gx, gy = x, y
        if preset.get("guess_positive"):
            ok = (x > 0) & (y > 0)
            gx, gy = x[ok], y[ok]
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                params = spec.lmfit_model.guess(gy, x=gx)
            if not all(math.isfinite(params[n].value) for n in spec.params):
                params = None
            else:
                guessed = set(spec.params)
        except Exception:  # noqa: BLE001 — some guesses fail on odd data
            params = None
        if params is not None:
            for name in preset.get("free") or ():
                params[name].set(expr="", vary=True)
    if params is None:
        params = spec.lmfit_model.make_params(**{n: 1.0 for n in spec.params})
        ns = _guess_namespace(x, y)
        for name, rule in (preset.get("guess") or {}).items():
            try:
                with np.errstate(all="ignore"):
                    val = float(eval(rule, ns))  # noqa: S307 — preset data, restricted namespace
                if math.isfinite(val):
                    params[name].set(value=val)
                    guessed.add(name)
            except Exception:  # noqa: BLE001 — fall back to 1
                pass
    for name, val in initial.items():
        params[name].set(value=val)
    return params, guessed


# ── fitting ───────────────────────────────────────────────────────────────────

def _columns(df, x_col: str, y_col: str, err_col: str | None):
    import numpy as np

    if df is None or len(df.columns) == 0:
        raise FitError("Curve fit needs input data: connect a node with your measurements")
    for label, col in (("x", x_col), ("y", y_col), ("y error", err_col)):
        if col and col not in df.columns:
            raise FitError(f"Column '{col}' (for {label}) is not in the input. Columns: {', '.join(map(str, df.columns))}")
    if not x_col or not y_col:
        raise FitError("Pick the x and y columns")
    cols = [x_col, y_col] + ([err_col] if err_col else [])
    try:
        data = df[cols].astype(float)
    except (TypeError, ValueError):
        raise FitError(f"Columns {', '.join(cols)} must be numeric") from None
    data = data[np.isfinite(data).all(axis=1)]
    x, y = data[x_col].to_numpy(), data[y_col].to_numpy()
    err = data[err_col].to_numpy() if err_col else None
    if err is not None and (err <= 0).any():
        raise FitError(f"'{err_col}' has zero or negative uncertainties; every y error must be > 0")
    return x, y, err


def fit(df, *, x: str, y: str, y_err: str | None = None, model: str = "linear",
        expression: str = "", variable: str = "x", initial: str = ""):
    """Fit and return (table DataFrame, lmfit ModelResult)."""
    import numpy as np
    import pandas as pd

    spec = build_model(model, expression, variable)
    xs, ys, err = _columns(df, x, y, y_err or None)
    n_free = len(spec.params)
    if len(xs) <= n_free:
        raise FitError(f"{len(xs)} data points can't determine {n_free} parameters; need at least {n_free + 1}")

    try:
        user_initial = parse_assignments(initial)
    except ExpressionError as exc:
        raise FitError(str(exc)) from None
    params, guessed = _initial_params(spec, xs, ys, user_initial)
    unguided = [p for p in spec.params if p not in user_initial and p not in guessed]

    def advice() -> str:
        need = unguided or [p for p in spec.params if p not in user_initial]
        if need:
            example = ", ".join(f"{p}=…" for p in need)
            return f"supply initial guesses for {', '.join(need)} (Initial guesses: {example})"
        return "try different initial guesses, or check that the model fits the shape of the data"

    weights = 1.0 / err if err is not None else None
    try:
        with np.errstate(all="ignore"):
            result = spec.lmfit_model.fit(
                ys, params, weights=weights, nan_policy="raise",
                # With measured uncertainties, report them as absolute (not
                # rescaled by the fit quality) — the convention for lab data.
                scale_covar=err is None,
                **{spec.variable: xs})
    except ValueError as exc:
        msg = str(exc)
        if "NaN" in msg or "nan" in msg:
            raise FitError(f"The model gives NaN at the starting values — {advice()}") from None
        raise FitError(f"Curve fit failed: {msg}") from None

    values = {n: result.params[n].value for n in spec.params}
    if not result.success or not all(np.isfinite(v) for v in values.values()):
        raise FitError(f"Fit did not converge ({result.message}) — {advice()}")
    if not result.errorbars:
        print("Warning: uncertainties could not be estimated (the parameters may be "
              f"correlated or poorly determined) — {advice()}")

    resid = ys - result.best_fit
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    r2 = 1 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    if not spec.linear and np.isfinite(r2) and r2 < MIN_R_SQUARED_NONLINEAR:
        raise FitError(f"The fit stopped far from the data (r² = {r2:.3f}), usually a wrong "
                       f"local minimum — {advice()}")

    rows = [("parameter", n, float(values[n]),
             float(result.params[n].stderr) if result.params[n].stderr is not None else np.nan, "")
            for n in spec.params]
    rows += [("statistic", "chi2", float(result.chisqr), np.nan, ""),
             ("statistic", "redchi", float(result.redchi), np.nan, ""),
             ("statistic", "r_squared", r2, np.nan, ""),
             ("statistic", "n_points", float(len(xs)), np.nan, ""),
             ("model", "expression", np.nan, np.nan, spec.expression),
             ("model", "variable", np.nan, np.nan, spec.variable),
             ("model", "preset", np.nan, np.nan, spec.preset),
             ("model", "x_column", np.nan, np.nan, str(x))]
    table = pd.DataFrame(rows, columns=list(TABLE_COLUMNS))
    return table, result
