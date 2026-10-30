"""Phase 0: the Curve fit engine.

Synthetic data with known parameters must be recovered; linear and weighted
fits must match the analytic least-squares solutions exactly.
"""
import numpy as np
import pandas as pd
import pytest

from sfs_plugin_curvefit import presets
from sfs_plugin_curvefit.expr import ExpressionError, parse
from sfs_plugin_curvefit.fit import TABLE_COLUMNS, FitError, build_model, fit

RNG = np.random.default_rng(7)

# True parameters and x range per preset. Noise is 1% of the peak |y|.
TRUE = {
    "linear": ({"slope": 2.5, "intercept": -1.0}, (0, 10)),
    "poly2": ({"c0": 1, "c1": -2, "c2": 0.5}, (-5, 5)),
    "poly3": ({"c0": 1, "c1": -2, "c2": 0.5, "c3": 0.1}, (-5, 5)),
    "poly4": ({"c0": 1, "c1": -2, "c2": 0.5, "c3": 0.1, "c4": -0.02}, (-5, 5)),
    "poly5": ({"c0": 1, "c1": -2, "c2": 0.5, "c3": 0.1, "c4": -0.02, "c5": 0.003}, (-5, 5)),
    "exp_decay": ({"amplitude": 5, "decay": 3}, (0, 15)),
    "exp_decay_offset": ({"amplitude": 5, "decay": 3, "c": 2}, (0, 15)),
    "exp_growth": ({"A": 2, "k": 0.3}, (0, 10)),
    "power_law": ({"amplitude": 3, "exponent": 1.7}, (0.5, 10)),
    "logistic": ({"L": 10, "k": 1.5, "x0": 4}, (0, 10)),
    "gaussian": ({"amplitude": 8, "center": 2, "sigma": 0.7}, (-2, 6)),
    "lorentzian": ({"amplitude": 8, "center": 2, "sigma": 0.5}, (-3, 7)),
    "voigt": ({"amplitude": 8, "center": 2, "sigma": 0.5, "gamma": 0.3}, (-3, 7)),
    "damped_oscillation": ({"A": 3, "tau": 4, "f": 0.8, "phi": 0.4, "C": 1}, (0, 10)),
    "arrhenius": ({"A": 1e7, "Ea": 50000}, (280, 380)),
    "michaelis_menten": ({"Vmax": 12, "Km": 2.5}, (0.1, 20)),
    "hill": ({"Vmax": 10, "K": 3, "n": 2.2}, (0.1, 12)),
    "logistic_growth": ({"K": 100, "N0": 5, "r": 0.8}, (0, 15)),
}


def _synthetic(preset_id, n=120, noise=0.01):
    true, (lo, hi) = TRUE[preset_id]
    spec = build_model(preset_id)
    params = spec.lmfit_model.make_params(**true)
    for name in presets.BY_ID[preset_id].get("free") or ():
        params[name].set(value=true[name], expr="", vary=True)
    xs = np.linspace(lo, hi, n)
    y0 = spec.lmfit_model.eval(params, **{spec.variable: xs})
    ys = y0 + RNG.normal(0, noise * np.max(np.abs(y0)), n)
    return pd.DataFrame({"x": xs, "y": ys}), true


def _params(table):
    p = table[table.kind == "parameter"].set_index("name")
    return p.value.to_dict(), p.stderr.to_dict()


def _stat(table, name):
    return table.set_index(["kind", "name"]).loc[("statistic", name), "value"]


def test_every_preset_has_a_recovery_case():
    assert set(TRUE) == set(presets.BY_ID)


@pytest.mark.parametrize("preset_id", list(TRUE))
def test_recovers_known_parameters_from_automatic_guesses(preset_id):
    df, true = _synthetic(preset_id)
    table, _ = fit(df, x="x", y="y", model=preset_id)
    values, errors = _params(table)
    for name, v in true.items():
        # Within 5 standard errors and 10 % — tight enough to catch a wrong
        # minimum, loose enough for the correlated pairs (Arrhenius A/Ea).
        assert abs(values[name] - v) <= max(5 * errors[name], 0.10 * abs(v)), (name, values[name], v)
    assert _stat(table, "r_squared") > 0.98


def test_table_schema_and_model_rows():
    df, _ = _synthetic("exp_decay")
    table, _ = fit(df, x="x", y="y", model="exp_decay")
    assert tuple(table.columns) == TABLE_COLUMNS
    model = table[table.kind == "model"].set_index("name").text.to_dict()
    assert model == {"expression": "amplitude*exp(-x/decay)", "variable": "x", "preset": "exp_decay",
                     "x_column": "x", "y_column": "y", "y_err_column": ""}
    assert _stat(table, "n_points") == len(df)
    # Arrow needs one type per column: value and stderr stay numeric.
    import pyarrow as pa
    t = pa.Table.from_pandas(table, preserve_index=False)
    assert pa.types.is_floating(t.schema.field("value").type)


def test_linear_matches_analytic_least_squares():
    x = np.linspace(0, 10, 25)
    y = 1.5 * x - 0.7 + RNG.normal(0, 0.4, x.size)
    table, _ = fit(pd.DataFrame({"x": x, "y": y}), x="x", y="y", model="linear")
    values, errors = _params(table)

    (slope, intercept), cov = np.polyfit(x, y, 1, cov=True)   # scaled by residual variance
    assert values["slope"] == pytest.approx(slope, rel=1e-9)
    assert values["intercept"] == pytest.approx(intercept, rel=1e-9)
    assert errors["slope"] == pytest.approx(np.sqrt(cov[0, 0]), rel=1e-6)
    assert errors["intercept"] == pytest.approx(np.sqrt(cov[1, 1]), rel=1e-6)
    assert _stat(table, "chi2") == pytest.approx(np.sum((y - (slope * x + intercept)) ** 2), rel=1e-9)


def test_weighted_fit_uses_y_err_as_absolute_sigma():
    x = np.linspace(1, 10, 30)
    sigma = 0.1 + 0.05 * x                        # errors grow with x
    y = 3.0 * x + 2.0 + RNG.normal(0, sigma)
    df = pd.DataFrame({"x": x, "y": y, "dy": sigma})

    weighted, _ = fit(df, x="x", y="y", y_err="dy", model="linear")
    plain, _ = fit(df, x="x", y="y", model="linear")
    wv, we = _params(weighted)
    pv, _ = _params(plain)

    # Analytic weighted least squares with absolute σ (np.polyfit w=1/σ, unscaled cov).
    (slope, intercept), cov = np.polyfit(x, y, 1, w=1 / sigma, cov="unscaled")
    assert wv["slope"] == pytest.approx(slope, rel=1e-8)
    assert wv["intercept"] == pytest.approx(intercept, rel=1e-8)
    assert we["slope"] == pytest.approx(np.sqrt(cov[0, 0]), rel=1e-6)
    assert we["intercept"] == pytest.approx(np.sqrt(cov[1, 1]), rel=1e-6)
    assert wv["slope"] != pytest.approx(pv["slope"], rel=1e-6)    # the weights changed the answer
    chi2 = np.sum(((y - (slope * x + intercept)) / sigma) ** 2)
    assert _stat(weighted, "chi2") == pytest.approx(chi2, rel=1e-8)
    assert _stat(weighted, "redchi") == pytest.approx(chi2 / (len(x) - 2), rel=1e-8)


def test_non_positive_errors_are_refused():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 2, 3, 4], "dy": [0.1, 0, 0.1, 0.1]})
    with pytest.raises(FitError, match="must be > 0"):
        fit(df, x="x", y="y", y_err="dy", model="linear")


def test_custom_expression_with_initial_guesses():
    t = np.linspace(0, 20, 100)
    y = 2.0 * np.exp(-t / 5.0) + 0.5 + RNG.normal(0, 0.01, t.size)
    df = pd.DataFrame({"time": t, "counts": y})
    table, _ = fit(df, x="time", y="counts", model="custom", expression="A*exp(-t/tau) + C",
                   variable="t", initial="A=1, tau=2, C=0")
    values, _ = _params(table)
    assert values["A"] == pytest.approx(2.0, rel=0.02)
    assert values["tau"] == pytest.approx(5.0, rel=0.02)
    assert values["C"] == pytest.approx(0.5, abs=0.02)
    assert list(values) == ["A", "tau", "C"]              # order of first appearance
    model = table[table.kind == "model"].set_index("name").text
    assert model["expression"] == "A*exp(-t/tau) + C" and model["variable"] == "t"


def test_caret_means_power():
    x = np.linspace(-3, 3, 40)
    df = pd.DataFrame({"x": x, "y": 0.5 * x**2 + 1 + RNG.normal(0, 0.01, x.size)})
    table, _ = fit(df, x="x", y="y", model="custom", expression="a*x^2 + b")
    values, _ = _params(table)
    assert values["a"] == pytest.approx(0.5, rel=0.02)


def test_wrong_minimum_names_the_parameters_to_guess():
    # An oscillation at 2.3 Hz started from the default f=1 settles in a wrong
    # local minimum; lmfit calls that success, the engine must not.
    t = np.linspace(0, 10, 400)
    y = 2 * np.sin(2 * np.pi * 2.3 * t + 0.3) + RNG.normal(0, 0.05, t.size)
    df = pd.DataFrame({"t": t, "y": y})
    with pytest.raises(FitError) as exc:
        fit(df, x="t", y="y", model="custom", expression="A*sin(2*pi*f*t + p)", variable="t",
            initial="A=1, p=0")
    msg = str(exc.value)
    assert "wrong local minimum" in msg and "supply initial guesses for f" in msg and "f=…" in msg

    # The advice works: with f guessed, the same fit succeeds.
    table, _ = fit(df, x="t", y="y", model="custom", expression="A*sin(2*pi*f*t + p)", variable="t",
                   initial="A=1, p=0, f=2.29")
    assert _params(table)[0]["f"] == pytest.approx(2.3, rel=1e-3)


def test_low_r_squared_is_a_result_for_linear_models():
    # Pure noise: the slope is consistent with zero, r² ≈ 0, and that's an answer.
    x = np.linspace(0, 10, 50)
    df = pd.DataFrame({"x": x, "y": RNG.normal(0, 1, x.size)})
    table, _ = fit(df, x="x", y="y", model="linear")
    assert _stat(table, "r_squared") < 0.1
    custom, _ = fit(df, x="x", y="y", model="custom", expression="a + b*x + c*sin(x)")
    assert _stat(custom, "r_squared") < 0.1          # linear in a, b, c: also allowed


def test_nan_at_start_is_explained():
    df = pd.DataFrame({"x": [1.0, 2, 3, 4, 5], "y": [1.0, 2, 3, 4, 5]})
    with pytest.raises(FitError, match="NaN at the starting values"):
        fit(df, x="x", y="y", model="custom", expression="a*log(x - b)", initial="a=1, b=10")


def test_unknown_initial_guess_name():
    df, _ = _synthetic("linear")
    with pytest.raises(FitError, match="unknown parameters: tau.*slope, intercept"):
        fit(df, x="x", y="y", model="linear", initial="tau=1")


def test_too_few_points_and_missing_columns():
    with pytest.raises(FitError, match="need at least 3"):
        fit(pd.DataFrame({"x": [1, 2], "y": [1, 2]}), x="x", y="y", model="linear")
    with pytest.raises(FitError, match="Column 'q'.*Columns: x, y"):
        fit(pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3]}), x="x", y="q", model="linear")
    with pytest.raises(FitError, match="connect a node"):
        fit(pd.DataFrame(), x="x", y="y", model="linear")


# ── expression parsing ────────────────────────────────────────────────────────

def test_parse_finds_parameters_and_evaluates():
    pm = parse("A*exp(-t/tau) + C", "t")
    assert pm.params == ["A", "tau", "C"]
    assert pm.func(np.array([0.0, 1.0]), 2.0, 1.0, 0.5) == pytest.approx([2.5, 2 * np.exp(-1) + 0.5])


def test_parse_names_unknown_functions():
    with pytest.raises(ExpressionError, match="Unknown functions: foo, __import__"):
        parse("foo(x) + __import__(x)", "x")


@pytest.mark.parametrize("expr, message", [
    ("", "empty"),
    ("a*y + b", "doesn't use the variable 'x'"),
    ("2*x + 1", "no parameters"),
    ("lambda*x", "Python keyword"),
    ("exp*x", "is a function"),
    ("a*x +", "Could not parse"),
])
def test_parse_errors(expr, message):
    with pytest.raises(ExpressionError, match=message):
        parse(expr, "x")


def test_names_that_are_sympy_builtins_are_plain_parameters():
    # gamma, beta, N, S, E are SymPy functions/constants; here they must be parameters.
    pm = parse("gamma*x + beta + N*S*E", "x")
    assert pm.params == ["gamma", "beta", "N", "S", "E"]
    assert pm.func(np.array([2.0]), 3.0, 1.0, 1.0, 1.0, 1.0) == pytest.approx([8.0])


def test_constants_pi_and_e():
    pm = parse("a*sin(pi*x) + e", "x")
    assert pm.params == ["a"]
    assert pm.func(np.array([0.5]), 2.0) == pytest.approx([2 + np.e])
