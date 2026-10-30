"""SFS plugin: curve fitting (lmfit) — registers the `curvefit_fit` engine.

Engine names are saved into every flow that uses them: never rename them.
Heavy libraries (lmfit, sympy, numpy) are imported inside `run`, so SFS starts
even when they are missing; the engine then shows as unavailable.
"""
from __future__ import annotations

from . import presets

FIT_HINT = """# Curve fit — fill the fields above, or take over here.
# If this cell is not empty it runs instead of the form, with:
#   df (upstream frame), lmfit, np  — leave your result in `df`.
#
# model = lmfit.models.ExponentialModel()
# params = model.guess(df["y"], x=df["t"])
# result = model.fit(df["y"], params, x=df["t"])
# df = pd.DataFrame({"name": list(result.params),
#                    "value": [p.value for p in result.params.values()]})
"""

FIT_PARAMS = (
    {"key": "x", "label": "x column", "type": "column", "required": True,
     "help": "Independent variable."},
    {"key": "y", "label": "y column", "type": "column", "required": True,
     "help": "Measured value."},
    {"key": "y_err", "label": "y error column (optional)", "type": "column",
     "help": "Uncertainty of each y. Points are weighted by 1/σ and the reported "
             "errors are absolute."},
    {"key": "model", "label": "Model", "type": "select", "default": "linear", "required": True,
     "options": presets.select_options()},
    {"key": "expression", "label": "Custom expression", "type": "string",
     "help": "Used when Model is Custom, e.g. A*exp(-t/tau) + C. "
             "Functions: exp log sqrt sin cos tan sinh cosh tanh abs; constants pi e."},
    {"key": "variable", "label": "Variable in the expression", "type": "string", "default": "x",
     "help": "Custom models only: the name standing for the x column, e.g. t."},
    {"key": "initial", "label": "Initial guesses (optional)", "type": "string",
     "help": "e.g. A=1, tau=2. Most presets guess automatically."},
)


def run_fit(ec):
    """Fit the model in the form, or run the node's own code if it has any."""
    if ec.code.strip():
        import lmfit
        import numpy as np

        scope = dict(ec.exec_globals)          # never mutate the shared dict
        scope.update({"lmfit": lmfit, "np": np, "df": ec.df_in,
                      "dfs": [ec.df_in] + list(ec.df_extra or [])})
        for i, extra in enumerate(ec.df_extra or [], start=2):
            scope[f"df{i}"] = extra
        if ec.preamble.strip():
            exec(ec.preamble, scope)  # noqa: S102
        exec(ec.code, scope)          # noqa: S102
        if scope.get("df") is None:
            raise ValueError("Curve fit code must leave a DataFrame in `df`")
        return scope["df"]

    from .fit import fit
    p = ec.params or {}
    table, _ = fit(ec.df_in, x=p.get("x"), y=p.get("y"), y_err=p.get("y_err") or None,
                   model=p.get("model") or "linear", expression=p.get("expression") or "",
                   variable=p.get("variable") or "x", initial=p.get("initial") or "")
    return table


def register(api):
    api.register_engine(api.EngineSpec(
        name="curvefit_fit",                 # permanent id — do not rename
        label="Curve fit",
        description="Fit a model to data · parameters ± errors",
        run=run_fit,
        input_mode="pandas",
        output_mode="pandas",
        language="python",
        tier="free",
        requires=("lmfit", "sympy", "numpy"),
        hint=FIT_HINT,
        params=FIT_PARAMS,
    ))
