"""SFS plugin: curve fitting (lmfit) — registers `curvefit_fit`, `curvefit_eval`
the "Fit with residuals" chart template and example flows.

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


def _run_code(ec, what: str):
    """The node's own code, run instead of the form (a student taking over)."""
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
        raise ValueError(f"{what} code must leave a DataFrame in `df`")
    return scope["df"]


def run_fit(ec):
    """Fit the model in the form, or run the node's own code if it has any."""
    if ec.code.strip():
        return _run_code(ec, "Curve fit")

    from .fit import fit
    p = ec.params or {}
    table, _ = fit(ec.df_in, x=p.get("x"), y=p.get("y"), y_err=p.get("y_err") or None,
                   model=p.get("model") or "linear", expression=p.get("expression") or "",
                   variable=p.get("variable") or "x", initial=p.get("initial") or "")
    return table


EVAL_HINT = """# Evaluate model — fill the fields above.
# Connect a Curve fit node to use its model and parameters; connect your data
# too for Columns mode. Inputs are told apart by their columns, not their order.
# If this cell is not empty it runs instead of the form, with df, dfs, df2…,
# lmfit and np — leave your result in `df`.
"""

EVAL_PARAMS = (
    {"key": "mode", "label": "Mode", "type": "select", "default": "range", "required": True,
     "options": [{"value": "range", "label": "Range — a smooth curve over start…stop"},
                 {"value": "columns", "label": "Columns — over the upstream rows"}]},
    {"key": "model", "label": "Model", "type": "select", "default": "from_fit", "required": True,
     "options": [{"value": "from_fit", "label": "From the connected fit", "group": "Fit"}]
                + presets.select_options()},
    {"key": "expression", "label": "Custom expression", "type": "string",
     "help": "Used when Model is Custom, e.g. m*g*h or A*exp(-t/tau) + C."},
    {"key": "variable", "label": "Variable in the expression", "type": "string", "default": "x",
     "help": "Custom models only: the independent variable, e.g. t."},
    {"key": "parameters", "label": "Parameters", "type": "string",
     "help": "e.g. A=2, tau=5. Ignored when a Curve fit node is connected."},
    {"key": "x", "label": "x column (Columns mode)", "type": "column",
     "help": "Column holding the model's variable. Default: the fit's x column, "
             "else the column named like the variable."},
    {"key": "start", "label": "Start", "type": "number", "help": "Range mode: first value of the variable."},
    {"key": "stop", "label": "Stop", "type": "number", "help": "Range mode: last value of the variable."},
    {"key": "points", "label": "Points", "type": "number", "default": 200, "help": "Range mode."},
    {"key": "output", "label": "Output column", "type": "string", "default": "value",
     "help": "Columns mode: name of the result column; uncertainties go in <name>_err. "
             "Other names in the expression are read from columns of that name, and "
             "<name>_err columns are propagated."},
)


def run_eval(ec):
    if ec.code.strip():
        return _run_code(ec, "Evaluate model")
    from .evaluate import EvalError, evaluate_columns, evaluate_range, split_inputs

    p = ec.params or {}
    table, data = split_inputs([ec.df_in] + list(ec.df_extra or []))
    common = {"model": p.get("model") or "from_fit", "expression": p.get("expression") or "",
              "variable": p.get("variable") or "x", "parameters": p.get("parameters") or ""}
    mode = p.get("mode") or "range"
    if mode == "range":
        return evaluate_range(table, start=p.get("start"), stop=p.get("stop"),
                              points=p.get("points") or 200, **common)
    if mode != "columns":
        raise EvalError(f"Unknown mode '{mode}'")
    if len(data) > 1:
        raise EvalError("Columns mode takes one data input (plus an optional Curve fit); "
                        f"{len(data)} data inputs are connected")
    return evaluate_columns(data[0] if data else None, table,
                            output=p.get("output") or "value", x=p.get("x") or "", **common)


def _to_code(api, name):
    """View as Python, on SFS versions whose EngineSpec has `to_code`."""
    import dataclasses
    if "to_code" not in {f.name for f in dataclasses.fields(api.EngineSpec)}:
        return {}

    def to_code(params, inputs):
        from . import codegen
        return getattr(codegen, name)(params, inputs)
    return {"to_code": to_code}


def _register_templates(api):
    # Older SFS without templates: the engines still work.
    if not hasattr(api, "register_template"):
        return
    from . import templates
    api.register_template(
        kind="chart", name="Fit with residuals",
        description="Data with error bars, the fitted curve and a residual panel. "
                    "Connect the measurements, Evaluate model (Range) and optionally Curve fit.",
        code=templates.read("fit_with_residuals"))


def _register_examples(api):
    if not hasattr(api, "register_example"):
        return
    from .examples import EXAMPLES
    for name, description, flow in EXAMPLES:
        api.register_example(name=name, description=description, flow=flow)


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
        **_to_code(api, "fit_code"),
    ))
    _register_templates(api)
    _register_examples(api)
    api.register_engine(api.EngineSpec(
        name="curvefit_eval",                # permanent id — do not rename
        label="Evaluate model",
        description="Model values over a range or rows · propagated errors",
        run=run_eval,
        input_mode="pandas",
        output_mode="pandas",
        language="python",
        tier="free",
        requires=("lmfit", "sympy", "numpy", "uncertainties"),
        hint=EVAL_HINT,
        params=EVAL_PARAMS,
        **_to_code(api, "eval_code"),
    ))
