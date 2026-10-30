"""Phase 3: View as Python.

The generated code is executed the way a pandas node runs it (df, dfs, pd) and
its output frame must equal the engine's.
"""
import numpy as np
import pandas as pd
import pytest

from sfs_plugin_curvefit import presets
from sfs_plugin_curvefit.codegen import eval_code, fit_code
from sfs_plugin_curvefit.evaluate import EvalError, evaluate_columns, evaluate_range, split_inputs
from sfs_plugin_curvefit.fit import FitError, fit

from test_fit import TRUE, _synthetic


def run_code(code, frames):
    frames = [f.copy() for f in frames]
    scope = {"pd": pd, "df": frames[0] if frames else pd.DataFrame(), "dfs": frames}
    exec(compile(code, "<generated>", "exec"), scope)  # noqa: S102
    return scope["df"]


def assert_same(engine, generated):
    assert list(engine.columns) == list(generated.columns)
    assert len(engine) == len(generated)
    for c in engine.columns:
        a, b = engine[c], generated[c]
        if pd.api.types.is_numeric_dtype(a):
            np.testing.assert_allclose(a.to_numpy(float), b.to_numpy(float), rtol=1e-9,
                                       atol=1e-12, equal_nan=True, err_msg=c)
        else:
            assert a.tolist() == b.tolist(), c


def compile_ok(code):
    compile(code, "<generated>", "exec")
    assert "\t" not in code


# ── Curve fit ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset_id", list(TRUE))
def test_every_preset_fit_as_code_matches(preset_id):
    df, _ = _synthetic(preset_id)
    params = {"x": "x", "y": "y", "model": preset_id}
    engine, _ = fit(df, **params)
    code = fit_code(params)
    compile_ok(code)
    assert_same(engine, run_code(code, [df]))


@pytest.mark.parametrize("params", [
    {"model": "custom", "expression": "A*exp(-t/tau) + C", "variable": "t",
     "initial": "A=1, tau=3, C=0", "y_err": "err"},
    {"model": "custom", "expression": "a*t^2 + b*abs(t) + c*sin(pi*t/10)", "variable": "t"},
    {"model": "exp_decay_offset", "y_err": "err", "initial": "decay=5"},
    {"model": "linear", "y_err": "err"},
])
def test_custom_and_weighted_fits_as_code_match(params):
    t = np.linspace(0.1, 20, 60)
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"t": t, "y": 4 * np.exp(-t / 6) + 1 + rng.normal(0, 0.03, t.size),
                       "err": 0.03, "junk": "a"})
    df.loc[5, "y"] = np.nan                      # dropped by both
    p = {"x": "t", "y": "y", **params}
    engine, _ = fit(df, **p)
    assert_same(engine, run_code(fit_code(p), [df]))


def test_fit_code_reads_like_a_lesson():
    code = fit_code({"x": "t", "y": "counts", "y_err": "err", "model": "custom",
                     "expression": "A*exp(-t/tau) + C", "variable": "t", "initial": "tau=5"})
    assert "def f(t, A, tau, C):\n    return A*np.exp(-t/tau) + C" in code
    assert "model = lmfit.Model(f, independent_vars=['t'])" in code
    assert "weights=1 / err, scale_covar=False" in code
    assert "params['tau'].set(value=5.0)" in code
    assert "sfs_plugin_curvefit" not in code            # plain lmfit, no plugin needed


def test_preset_guess_rules_and_helpers_appear_verbatim():
    code = fit_code({"x": "x", "y": "y", "model": "damped_oscillation"})
    assert "def dominant_freq(xs, ys):" in code and "'f': dominant_freq(x, y)," in code
    assert "def linfit" not in code                      # only the helpers it uses


def test_fit_code_needs_columns():
    with pytest.raises(FitError, match="x and y"):
        fit_code({"model": "linear"})


# ── Evaluate model ────────────────────────────────────────────────────────────

def _fit_inputs():
    t = np.linspace(0, 20, 40)
    rng = np.random.default_rng(2)
    data = pd.DataFrame({"t_s": t, "counts": 4 * np.exp(-t / 6) + 1 + rng.normal(0, 0.02, t.size),
                         "t_s_err": 0.1})
    table, _ = fit(data, x="t_s", y="counts", model="exp_decay_offset")
    return data, table


def _engine_eval(params, frames):
    table, data = split_inputs(frames)
    common = {k: params[k] for k in ("model", "expression", "variable", "parameters") if k in params}
    if params.get("mode", "range") == "range":
        return evaluate_range(table, start=params.get("start"), stop=params.get("stop"),
                              points=params.get("points", 200), **common)
    return evaluate_columns(data[0] if data else None, table, output=params.get("output", "value"),
                            x=params.get("x", ""), **common)


EVAL_CASES = {
    "range from fit": ({"mode": "range", "start": 0, "stop": 20, "points": 50}, "fit"),
    "columns from fit, propagated": ({"mode": "columns", "output": "fit"}, "fit+data"),
    "columns from fit, no errors": ({"mode": "columns"}, "fit+data-noerr"),
    "range, preset + parameters": ({"mode": "range", "model": "gaussian",
                                    "parameters": "amplitude=2, center=1, sigma=0.5",
                                    "start": -2, "stop": 4, "points": 30}, None),
    "range, voigt": ({"mode": "range", "model": "voigt",
                      "parameters": "amplitude=2, center=1, sigma=0.5, gamma=0.2",
                      "start": -2, "stop": 4, "points": 30}, None),
    "range, constant": ({"mode": "range", "model": "custom", "expression": "2*pi*r",
                         "parameters": "r=1", "start": 0, "stop": 1, "points": 3}, None),
    "columns, formula": ({"mode": "columns", "model": "custom", "expression": "m*g*h",
                          "parameters": "g=9.81"}, "mgh"),
    "columns, abs": ({"mode": "columns", "model": "custom", "expression": "a*abs(x) + sin(x)",
                      "parameters": "a=2"}, "abs"),
    "columns, x field": ({"mode": "columns", "model": "linear", "parameters": "slope=3, intercept=1",
                          "x": "time"}, "time"),
    "columns, constant": ({"mode": "columns", "model": "custom", "expression": "2*pi*r",
                           "parameters": "r=1"}, "mgh"),
    "columns, voigt": ({"mode": "columns", "model": "voigt",
                        "parameters": "amplitude=2, center=1, sigma=0.5, gamma=0.2"}, "voigt"),
}


def _frames(kind):
    data, table = _fit_inputs()
    return {
        None: [],
        "fit": [table],
        "fit+data": [data, table],
        "fit+data-noerr": [table, data.drop(columns="t_s_err")],
        "mgh": [pd.DataFrame({"m": [1.0, 2.0], "m_err": [0.1, 0.05], "h": [3.0, 0.5], "h_err": [0.2, 0.01]})],
        "abs": [pd.DataFrame({"x": [-2.0, 3.0], "x_err": [0.1, 0.1]})],
        "time": [pd.DataFrame({"time": [0.0, 2.0], "time_err": [0.1, 0.1]})],
        "voigt": [pd.DataFrame({"x": np.linspace(-1, 3, 9)})],
    }[kind]


@pytest.mark.parametrize("case", list(EVAL_CASES))
def test_evaluate_as_code_matches(case):
    params, kind = EVAL_CASES[case]
    frames = _frames(kind)
    engine = _engine_eval(params, frames)
    code = eval_code(params, frames)
    compile_ok(code)
    assert_same(engine, run_code(code, frames))


def test_generated_code_finds_the_fit_in_either_order():
    data, table = _fit_inputs()
    code = eval_code({"mode": "columns"}, [data, table])
    assert_same(run_code(code, [data, table]), run_code(code, [table, data]))


def test_from_fit_needs_a_run_first():
    with pytest.raises(EvalError, match="Run the flow once"):
        eval_code({"mode": "range", "start": 0, "stop": 1}, [])


def test_missing_parameters_are_named_in_code_generation():
    with pytest.raises(EvalError, match="Missing parameter values: A, tau"):
        eval_code({"mode": "range", "model": "custom", "expression": "A*exp(-x/tau)",
                   "start": 0, "stop": 1}, [])


def test_every_preset_evaluates_as_code():
    for p in presets.PRESETS:
        from sfs_plugin_curvefit.fit import build_model
        names = build_model(p["id"]).params
        params = {"mode": "range", "model": p["id"], "start": 0.5, "stop": 5, "points": 20,
                  "parameters": ", ".join(f"{n}={1 + i / 10}" for i, n in enumerate(names))}
        assert_same(_engine_eval(params, []), run_code(eval_code(params, []), []))
