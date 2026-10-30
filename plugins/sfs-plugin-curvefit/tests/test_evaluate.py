"""Phase 1: the Evaluate model engine.

Range and columns modes, parameter-table detection by schema, and uncertainty
propagation checked against the analytic first-order formula.
"""
import numpy as np
import pandas as pd
import pytest

from sfs_plugin_curvefit import presets
from sfs_plugin_curvefit.evaluate import (EvalError, evaluate_columns, evaluate_range,
                                          is_parameter_table, split_inputs)
from sfs_plugin_curvefit.fit import build_model, fit

RNG = np.random.default_rng(11)


def _decay_data(n=80):
    t = np.linspace(0, 20, n)
    y = 4 * np.exp(-t / 6) + 1 + RNG.normal(0, 0.02, n)
    return pd.DataFrame({"t": t, "y": y, "y_err": 0.02})


def _decay_table():
    table, result = fit(_decay_data(), x="t", y="y", y_err="y_err", model="custom",
                        expression="A*exp(-t/tau) + C", variable="t", initial="A=1, tau=3, C=0")
    return table, result


# ── fit → evaluate chain ──────────────────────────────────────────────────────

def test_range_from_a_fit_matches_lmfit():
    table, result = _decay_table()
    out = evaluate_range(table, start=0, stop=20, points=50)
    assert list(out.columns) == ["t", "value"] and len(out) == 50
    expected = result.model.eval(result.params, t=out["t"].to_numpy())
    np.testing.assert_allclose(out["value"], expected, rtol=1e-12)


def test_columns_from_a_fit_gives_the_best_fit():
    data = _decay_data()
    table, result = fit(data, x="t", y="y", model="custom", expression="A*exp(-t/tau) + C",
                        variable="t", initial="A=1, tau=3, C=0")
    out = evaluate_columns(data, table, output="fit")
    np.testing.assert_allclose(out["fit"], result.best_fit, rtol=1e-12)
    assert list(out.columns) == ["t", "y", "y_err", "fit"]   # rows kept, column added


@pytest.mark.parametrize("preset_id", [p["id"] for p in presets.PRESETS])
def test_every_preset_evaluates_like_lmfit(preset_id):
    """The written-out expression of each preset is lmfit's model, exactly."""
    spec = build_model(preset_id)
    rng = np.random.default_rng(3)
    values = {n: float(rng.uniform(0.5, 2.0)) for n in spec.params}
    params = spec.lmfit_model.make_params(**values)
    for name in presets.BY_ID[preset_id].get("free") or ():
        params[name].set(value=values[name], expr="")
    xs = np.linspace(0.5, 5, 40)
    expected = spec.lmfit_model.eval(params, **{spec.variable: xs})
    text = ", ".join(f"{k}={v!r}" for k, v in values.items())
    out = evaluate_range(model=preset_id, parameters=text, start=0.5, stop=5, points=40)
    np.testing.assert_allclose(out["value"], expected, rtol=1e-10)
    assert out.columns[0] == spec.variable


def test_explicit_model_overrides_the_table_model():
    table, _ = _decay_table()
    out = evaluate_range(table, model="custom", expression="A + C", variable="t",
                         start=0, stop=1, points=2)
    p = table[table.kind == "parameter"].set_index("name").value
    np.testing.assert_allclose(out["value"], p["A"] + p["C"])


# ── parameter table detection ─────────────────────────────────────────────────

def test_parameter_table_is_found_by_schema_not_position():
    table, _ = _decay_table()
    data = _decay_data()
    assert is_parameter_table(table) and not is_parameter_table(data)
    for order in ([table, data], [data, table]):
        found, rest = split_inputs(order)
        assert found is table and rest == [data]


def test_zero_column_trigger_frames_are_ignored():
    found, rest = split_inputs([pd.DataFrame(), None])
    assert found is None and rest == []


def test_two_parameter_tables_are_refused():
    table, _ = _decay_table()
    with pytest.raises(EvalError, match="More than one parameter table"):
        split_inputs([table, table.copy()])


def test_parameters_string_is_ignored_when_a_table_is_connected(capsys):
    table, result = _decay_table()
    out = evaluate_range(table, parameters="A=100", start=0, stop=0, points=2)
    assert out["value"][0] == pytest.approx(result.params["A"].value + result.params["C"].value)
    assert "ignored" in capsys.readouterr().out


# ── columns mode, propagation ─────────────────────────────────────────────────

def test_formula_over_columns_with_parameters():
    df = pd.DataFrame({"m": [1.0, 2.0], "h": [3.0, 0.5]})
    out = evaluate_columns(df, model="custom", expression="m*g*h", parameters="g=9.81")
    np.testing.assert_allclose(out["value"], [29.43, 9.81])
    assert "value_err" not in out


def test_error_columns_are_propagated():
    """σ_f² = Σ (∂f/∂v σ_v)² for f = m*g*h, independent m and h."""
    df = pd.DataFrame({"m": [1.0, 2.0], "m_err": [0.1, 0.05], "h": [3.0, 0.5], "h_err": [0.2, 0.01]})
    out = evaluate_columns(df, model="custom", expression="m*g*h", parameters="g=9.81")
    g = 9.81
    expected = np.hypot(g * df.h * df.m_err, g * df.m * df.h_err)
    np.testing.assert_allclose(out["value_err"], expected, rtol=1e-12)


def test_propagation_through_a_nonlinear_fitted_model():
    table, result = _decay_table()
    df = pd.DataFrame({"t": [1.0, 5.0, 10.0], "t_err": [0.1, 0.2, 0.0]})
    out = evaluate_columns(df, table)
    A, tau = result.params["A"].value, result.params["tau"].value
    dfdt = -A / tau * np.exp(-df.t / tau)
    np.testing.assert_allclose(out["value_err"], np.abs(dfdt) * df.t_err, rtol=1e-10)
    np.testing.assert_allclose(out["value"], result.model.eval(result.params, t=df.t.to_numpy()))


def test_propagation_through_abs_and_functions():
    df = pd.DataFrame({"x": [-2.0, 3.0], "x_err": [0.1, 0.1]})
    out = evaluate_columns(df, model="custom", expression="a*abs(x) + sin(x)", parameters="a=2")
    expected = np.abs(2 * np.sign(df.x) + np.cos(df.x)) * 0.1
    np.testing.assert_allclose(out["value_err"], expected, rtol=1e-12)


def test_output_column_name():
    df = pd.DataFrame({"x": [1.0], "x_err": [0.5]})
    out = evaluate_columns(df, model="linear", parameters="slope=2, intercept=1", output="pred")
    assert out["pred"][0] == 3 and out["pred_err"][0] == pytest.approx(1.0)


def test_voigt_evaluates_through_lmfit_in_columns_mode():
    df = pd.DataFrame({"x": np.linspace(-1, 3, 9)})
    out = evaluate_columns(df, model="voigt", parameters="amplitude=2, center=1, sigma=0.4, gamma=0.2")
    ref = evaluate_range(model="voigt", parameters="amplitude=2, center=1, sigma=0.4, gamma=0.2",
                         start=-1, stop=3, points=9)
    np.testing.assert_allclose(out["value"], ref["value"])
    with pytest.raises(EvalError, match="Uncertainty propagation isn't available"):
        evaluate_columns(df.assign(x_err=0.1), model="voigt",
                         parameters="amplitude=2, center=1, sigma=0.4, gamma=0.2")


# ── messages ──────────────────────────────────────────────────────────────────

def test_from_fit_without_a_fit_says_what_to_do():
    with pytest.raises(EvalError, match="connect a Curve fit node, or pick a Model"):
        evaluate_range(start=0, stop=1)


def test_missing_parameters_are_named():
    with pytest.raises(EvalError, match="Missing parameter values: A, tau"):
        evaluate_range(model="custom", expression="A*exp(-x/tau)", start=0, stop=1)


def test_range_needs_start_and_stop():
    with pytest.raises(EvalError, match="Start and Stop"):
        evaluate_range(model="linear", parameters="slope=1, intercept=0", stop=1)


def test_unresolved_names_list_the_columns():
    df = pd.DataFrame({"a": [1.0]})
    with pytest.raises(EvalError, match=r"No value for x.*Columns: a"):
        evaluate_columns(df, model="linear", parameters="slope=1, intercept=0")


def test_columns_mode_needs_data():
    with pytest.raises(EvalError, match="needs data"):
        evaluate_columns(pd.DataFrame(), model="linear", parameters="slope=1, intercept=0")


def test_constant_expression_fills_every_row():
    df = pd.DataFrame({"q": [1.0, 2.0, 3.0]})
    out = evaluate_columns(df, model="custom", expression="2*pi*r", parameters="r=1")
    np.testing.assert_allclose(out["value"], 2 * np.pi)


# ── which column holds the variable ───────────────────────────────────────────

def test_x_column_field_maps_the_variable_and_its_error():
    df = pd.DataFrame({"time": [0.0, 2.0], "time_err": [0.1, 0.1]})
    out = evaluate_columns(df, model="linear", parameters="slope=3, intercept=1", x="time")
    np.testing.assert_allclose(out["value"], [1, 7])
    np.testing.assert_allclose(out["value_err"], [0.3, 0.3])
    assert list(out.columns) == ["time", "time_err", "value", "value_err"]


def test_fits_x_column_is_used_by_default():
    data = pd.DataFrame({"time": np.arange(10.0)}).assign(y=lambda d: 2 * d.time + 1)
    table, _ = fit(data, x="time", y="y", model="linear")
    out = evaluate_columns(data, table)
    np.testing.assert_allclose(out["value"], data.y, rtol=1e-9)
    assert evaluate_range(table, start=0, stop=1, points=2).columns[0] == "time"


def test_unknown_x_column_is_named():
    with pytest.raises(EvalError, match="Column 'nope'"):
        evaluate_columns(pd.DataFrame({"x": [1.0]}), model="linear",
                         parameters="slope=1, intercept=0", x="nope")
