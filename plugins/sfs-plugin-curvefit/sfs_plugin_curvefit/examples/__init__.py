"""Example flows shipped with the plugin: sample data → Curve fit → Evaluate
model → Fit with residuals. Users start a new project from one in the project
picker (Start from an example).

The data files sit next to this module; the flows' load nodes read them with
importlib.resources, so the examples work in any install, Docker included.
"""
from __future__ import annotations

from importlib import resources

from .. import templates


def data_path(name: str):
    return resources.files(__name__).joinpath(name)


def _edge(source: str, target: str) -> dict:
    return {"id": f"e-{source}-{target}", "source": source, "target": target,
            "sourceHandle": "out", "targetHandle": "in"}


def _node(node_id: str, node_type: str, at: tuple[int, int], **data) -> dict:
    return {"id": node_id, "type": node_type, "position": {"x": at[0], "y": at[1]}, "data": data}


def _chart(title: str, x_label: str, y_label: str) -> str:
    code = templates.read("fit_with_residuals")
    for key, value in (("TITLE", title), ("X_LABEL", x_label), ("Y_LABEL", y_label)):
        code = code.replace(f'{key} = ""', f"{key} = {value!r}", 1)
    return code


def _load_code(intro: str, filename: str, extra: str = "") -> str:
    return (f"{intro}\n"
            "# Sample data shipped with the curve-fit plugin. For your own measurements:\n"
            "#   df = pd.read_csv('/data/imports/my_data.csv')\n"
            "from importlib.resources import files\n"
            "import numpy as np\n\n"
            f"df = pd.read_csv(files('sfs_plugin_curvefit.examples') / {filename!r})\n"
            + extra)


# ── Physics: radioactive decay ────────────────────────────────────────────────

HALF_LIFE_CODE = """\
# Half-life from the fitted mean life τ:   t½ = τ·ln 2,   λ = 1/τ
# The errors follow the same rules:  σ(t½) = σ(τ)·ln 2,   σ(λ) = σ(τ)/τ²
import numpy as np

p = df[df["kind"] == "parameter"].set_index("name")
tau, tau_err = p.loc["decay", "value"], p.loc["decay", "stderr"]

df = pd.DataFrame({
    "quantity": ["mean life τ", "half-life t½", "decay constant λ"],
    "value": [tau, tau * np.log(2), 1 / tau],
    "error": [tau_err, tau_err * np.log(2), tau_err / tau**2],
})
"""

RADIOACTIVE_DECAY = {
    "name": "Radioactive decay",
    "nodes": [
        _node("start", "trigger", (40, 260), label="Start", run_mode="manual", cron="", timezone="UTC"),
        _node("note", "annotation", (300, 0), color="slate", fontSize=13, text=(
            "Radioactive decay: fit A·e^(−t/τ) to the counts, then t½ = τ·ln 2.\n"
            "Counting errors are √N. Click Run Flow, then open the Fit plot and Half-life nodes.\n"
            "Try: View as Python on the fit node, or the 'Exponential decay + offset' model.")),
        _node("counts", "processor", (300, 260), label="Decay counts", engine="pandas", code=_load_code(
            "# Radioactive decay: activity (counts) every 10 time units.",
            "radioactive_decay.csv",
            "# Counting statistics: the uncertainty of N counts is √N\n"
            "df['Activity_err'] = np.sqrt(df['Activity'])\n")),
        _node("fit", "processor", (620, 160), label="Fit exponential decay", engine="curvefit_fit", code="",
              x="Time", y="Activity", y_err="Activity_err", model="exp_decay"),
        _node("curve", "processor", (940, 60), label="Fitted curve", engine="curvefit_eval", code="",
              mode="range", model="from_fit", start=0, stop=100, points=200),
        _node("halflife", "processor", (940, 330), label="Half-life", engine="pandas", code=HALF_LIFE_CODE),
        _node("plot", "chart_out", (1260, 160), label="Fit plot",
              code=_chart("Radioactive decay", "time", "activity (counts)")),
        _node("result", "table_out", (1260, 400), label="Half-life"),
    ],
    "edges": [_edge("start", "counts"), _edge("counts", "fit"), _edge("fit", "curve"),
              _edge("fit", "halflife"), _edge("halflife", "result"),
              _edge("counts", "plot"), _edge("fit", "plot"), _edge("curve", "plot")],
}


# ── Biochemistry: enzyme kinetics ─────────────────────────────────────────────

ENZYME_KINETICS = {
    "name": "Enzyme kinetics",
    "nodes": [
        _node("start", "trigger", (40, 220), label="Start", run_mode="manual", cron="", timezone="UTC"),
        _node("note", "annotation", (300, 0), color="slate", fontSize=13, text=(
            "Enzyme kinetics: initial rate v against substrate concentration [S].\n"
            "Fit Michaelis–Menten v = Vmax·[S]/(Km + [S]) with the replicate errors.\n"
            "Try: the Hill equation model, to test for cooperativity (n ≠ 1).")),
        _node("rates", "processor", (300, 220), label="Initial rates", engine="pandas", code=_load_code(
            "# Initial reaction rates (µM/min) at substrate concentrations S (mM),\n"
            "# with the standard deviation of replicate measurements.",
            "enzyme_kinetics.csv")),
        _node("fit", "processor", (620, 140), label="Fit Michaelis–Menten", engine="curvefit_fit", code="",
              x="S_mM", y="rate", y_err="rate_err", model="michaelis_menten"),
        _node("curve", "processor", (940, 60), label="Fitted curve", engine="curvefit_eval", code="",
              mode="range", model="from_fit", start=0, stop=20, points=200),
        _node("params", "table_out", (940, 320), label="Vmax and Km"),
        _node("plot", "chart_out", (1260, 160), label="Fit plot",
              code=_chart("Michaelis–Menten kinetics", "[S] (mM)", "v (µM/min)")),
    ],
    "edges": [_edge("start", "rates"), _edge("rates", "fit"), _edge("fit", "curve"),
              _edge("fit", "params"), _edge("rates", "plot"), _edge("fit", "plot"),
              _edge("curve", "plot")],
}

EXAMPLES = (
    ("Curve fit · Radioactive decay (physics)",
     "Decay counts with √N errors → exponential fit → half-life with its error, and the fit plot.",
     RADIOACTIVE_DECAY),
    ("Curve fit · Enzyme kinetics (biochemistry)",
     "Initial rates with replicate errors → Michaelis–Menten fit → Vmax, Km and the fit plot.",
     ENZYME_KINETICS),
)
