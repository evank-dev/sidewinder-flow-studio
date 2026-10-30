"""Phase 2: the "Fit with residuals" chart template.

The template is run the way a Chart node runs it (code with df, df2, …, dfs),
in every input order, and its residuals are checked against the fit.
"""
import itertools

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from sfs_plugin_curvefit import templates  # noqa: E402
from sfs_plugin_curvefit.evaluate import evaluate_range  # noqa: E402
from sfs_plugin_curvefit.fit import fit  # noqa: E402

CODE = templates.read("fit_with_residuals")
RNG = np.random.default_rng(5)


def _inputs():
    t = np.linspace(0, 30, 40)
    data = pd.DataFrame({"t_s": t, "counts": 120 * np.exp(-t / 8) + 15 + RNG.normal(0, 2, t.size),
                         "err": 2.0})
    table, result = fit(data, x="t_s", y="counts", y_err="err", model="exp_decay_offset")
    curve = evaluate_range(table, start=0, stop=30, points=200)
    return data, table, curve, result


def _run(frames):
    plt.close("all")
    scope = {"pd": pd, "dfs": frames, "df": frames[0]}
    for i, f in enumerate(frames[1:], start=2):
        scope[f"df{i}"] = f
    exec(CODE, scope)  # noqa: S102
    return scope


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_any_input_order_gives_exact_residuals(order):
    data, table, curve, result = _inputs()
    frames = [(data, table, curve)[i] for i in order]
    s = _run(frames)
    assert (s["X"], s["Y"], s["Y_ERR"]) == ("t_s", "counts", "err")
    np.testing.assert_allclose(s["residuals"], data["counts"] - result.best_fit, atol=1e-9)
    fig = plt.gcf()
    assert len(fig.axes) == 2
    box = fig.axes[0].texts[0].get_text()
    assert "amplitude*exp(-x/decay) + c" in box and "decay = " in box and "χ²/ν" in box


def test_without_the_fit_residuals_come_from_the_curve():
    data, _, curve, result = _inputs()
    s = _run([curve, data.rename(columns={"err": "counts_err"})])
    assert (s["X"], s["Y"], s["Y_ERR"]) == ("t_s", "counts", "counts_err")
    # 200-point curve: interpolation is close to, not equal to, the exact model
    np.testing.assert_allclose(s["residuals"], data["counts"] - result.best_fit, atol=0.05)
    assert len(plt.gcf().axes[0].texts) == 0      # no parameter box without the fit


def test_curve_must_cover_the_data(capsys):
    data, _, _, _ = _inputs()
    short = pd.DataFrame({"t_s": [0.0, 10.0], "value": [1.0, 2.0]})
    s = _run([data.drop(columns="err"), short])
    assert np.isnan(s["residuals"]).any()
    assert "widen Start/Stop" in capsys.readouterr().out


def test_settings_at_the_top_override():
    data, table, curve, _ = _inputs()
    code = CODE.replace('TITLE = ""', 'TITLE = "Decay"', 1)
    plt.close("all")
    exec(code, {"pd": pd, "dfs": [data, table, curve]})  # noqa: S102
    assert plt.gcf().axes[0].get_title() == "Decay"


@pytest.mark.parametrize("frames, message", [
    (lambda d, t, c: [d, t], "Evaluate model node in Range mode"),
    (lambda d, t, c: [t, c], "exactly one measurements node"),
])
def test_missing_inputs_say_what_to_connect(frames, message):
    data, table, curve, _ = _inputs()
    with pytest.raises(ValueError, match=message):
        _run(frames(data, table, curve))


def test_ambiguous_y_asks_to_set_it():
    data, _, curve, _ = _inputs()
    with pytest.raises(ValueError, match="Set Y at the top"):
        _run([curve, data.assign(other=1.0)])
