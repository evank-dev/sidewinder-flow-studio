"""
Example SFS plugin — a scikit-learn execution engine.

This is a complete, working reference implementation of the SFS plugin
contract (docs/PLUGINS.md). Copy this package as a starting point for your own
engine.

What it adds: a "scikit-learn" engine for processor nodes. Node code is Python
with the upstream frame as `df`, plus scikit-learn pre-injected and a
`quick_model()` helper so common cases need one line.

Note on isolation: this is an *in-process* plugin — scikit-learn is installed
into the same environment as SFS. That's acceptable for scikit-learn, which
coexists with the core stack. Libraries with aggressive pins (PyCaret and
friends) should instead use the isolated runtime, where the heavy library lives
in its own virtual environment and data crosses as Arrow. The registration
contract below is identical either way — only `run` changes.
"""
from __future__ import annotations

HINT = """# scikit-learn engine — `df` is the upstream DataFrame.
# Pre-injected: sklearn, np, train_test_split, quick_model(...)
#
# One-liner: train a model and append predictions
# df, metrics = quick_model(df, target="churned")
#
# Or use scikit-learn directly:
# from sklearn.ensemble import GradientBoostingClassifier
# X = df[["tenure", "monthly_spend"]]; y = df["churned"]
# model = GradientBoostingClassifier().fit(X, y)
# df["prediction"] = model.predict(X)
#
# Leave the result in `df`.
"""


def _build_helpers():
    """Import scikit-learn lazily and build the names injected into node code.

    Heavy imports MUST happen inside run() (or a function it calls), never at
    module import time — otherwise SFS fails to start when the dependency is
    absent, instead of simply showing the engine as unavailable.
    """
    import numpy as np
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score, r2_score, mean_absolute_error
    import sklearn
    import pandas as pd

    MODELS = {
        "rf_classifier":  RandomForestClassifier,
        "rf_regressor":   RandomForestRegressor,
        "logistic":       LogisticRegression,
        "linear":         LinearRegression,
    }

    def quick_model(df, target: str, features: list[str] | None = None,
                    kind: str | None = None, test_size: float = 0.2,
                    random_state: int = 42, **model_kwargs):
        """Fit a model on `df` and return (df_with_predictions, metrics).

        `kind` defaults to a classifier for non-numeric or low-cardinality
        targets, a regressor otherwise. Non-numeric feature columns are dropped
        (encode them yourself upstream if you need them).
        """
        if target not in df.columns:
            raise ValueError(f"target column '{target}' not in frame. Columns: {list(df.columns)}")

        y = df[target]
        if features:
            missing = [c for c in features if c not in df.columns]
            if missing:
                raise ValueError(f"feature columns not in frame: {missing}")
            X = df[features]
        else:
            X = df.drop(columns=[target])
        X = X.select_dtypes(include="number")
        if X.empty:
            raise ValueError("no numeric feature columns available after filtering")

        if kind is None:
            is_classification = (not pd.api.types.is_numeric_dtype(y)) or y.nunique() <= 20
            kind = "rf_classifier" if is_classification else "rf_regressor"
        if kind not in MODELS:
            raise ValueError(f"unknown kind '{kind}'. Options: {list(MODELS)}")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )
        model = MODELS[kind](**model_kwargs).fit(X_train, y_train)

        preds_test = model.predict(X_test)
        if kind in ("rf_classifier", "logistic"):
            metrics = {
                "model": kind,
                "accuracy": round(float(accuracy_score(y_test, preds_test)), 4),
                "f1_weighted": round(float(f1_score(y_test, preds_test, average="weighted")), 4),
            }
        else:
            metrics = {
                "model": kind,
                "r2": round(float(r2_score(y_test, preds_test)), 4),
                "mae": round(float(mean_absolute_error(y_test, preds_test)), 4),
            }
        metrics["n_train"] = int(len(X_train))
        metrics["n_test"] = int(len(X_test))
        metrics["features"] = list(X.columns)

        out = df.copy()
        out["prediction"] = model.predict(X)
        return out, metrics

    return {
        "sklearn": sklearn,
        "np": np,
        "train_test_split": train_test_split,
        "quick_model": quick_model,
        **{name: cls for name, cls in MODELS.items()},
    }


def run_sklearn(ec):
    """Execute the node's code with scikit-learn available.

    `ec` is an EngineContext. Because input_mode="pandas", `ec.df_in` holds the
    upstream frame and `ec.df_extra` any additional inputs.
    """
    # Copy exec_globals — never mutate the context's dict (it is shared).
    scope = dict(ec.exec_globals)
    scope.update(_build_helpers())

    scope["df"] = ec.df_in
    for i, extra in enumerate(ec.df_extra or [], start=2):
        scope[f"df{i}"] = extra
    scope["dfs"] = [ec.df_in] + list(ec.df_extra or [])

    # Declared params arrive resolved (defaults applied) in ec.params.
    # They're also exposed to node code as plain names, so a user can mix the
    # form fields with custom code: quick_model(df, target=TARGET).
    p = ec.params or {}
    target = p.get("target")
    if target:
        scope["TARGET"] = target

    # No code? If the form gave us a target, just train — otherwise pass through.
    if not ec.code.strip():
        if not target:
            return ec.df_in
        kind = p.get("kind") or None
        if kind in ("auto", "", None):
            kind = None
        out, metrics = scope["quick_model"](
            ec.df_in, target=target, kind=kind,
            test_size=p.get("test_size", 0.2) or 0.2,
        )
        if p.get("show_metrics"):
            print("metrics:", metrics)
        return out

    # The flow preamble (imports + shared functions) must run first so the
    # user's shared helpers are available here, exactly as in other engines.
    if ec.preamble.strip():
        exec(ec.preamble, scope)  # noqa: S102
    exec(ec.code, scope)          # noqa: S102

    result = scope.get("df")
    if result is None:
        raise ValueError(
            "scikit-learn node must leave a DataFrame in `df` "
            "(e.g. `df, metrics = quick_model(df, target='y')`)"
        )
    return result


# ── Isolated variant ──────────────────────────────────────────────────────────
# Same capability, but executed in a separate interpreter with its own pinned
# dependencies. SFS hands the frame over as an Arrow file and never imports
# scikit-learn itself. This is the pattern for libraries that would otherwise
# fight the core environment (PyCaret and friends).

def _runner_path() -> str:
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")


def make_run_isolated(api):
    def run_sklearn_isolated(ec):
        venv = (ec.params or {}).get("venv") or "sklearn"
        table, info = api.run_isolated(
            venv=venv,
            runner=_runner_path(),
            inputs=[ec.df_in] if ec.df_in is not None else [],
            params=ec.params or {},
            code=ec.code,
            meta={"node": ec.node_data.get("label")},
        )
        if info.get("log"):
            print(info["log"])
        return table
    return run_sklearn_isolated


def register(api):
    """Entry point called once by SFS at startup.

    `api` exposes EngineSpec, EngineContext and register_engine. Keep this
    function cheap and side-effect free apart from registration — if it raises,
    SFS logs the failure and skips the plugin.
    """
    api.register_engine(api.EngineSpec(
        name="sklearn",
        label="scikit-learn",
        description="Train models on the frame",
        run=run_sklearn,
        input_mode="pandas",     # give me ready pandas DataFrames
        output_mode="pandas",    # I return a pandas DataFrame
        language="python",       # editor syntax highlighting
        tier="free",
        requires=("sklearn",),   # greyed out in the UI if not installed
        hint=HINT,
        # Declarative params → the node panel renders these fields above the
        # code editor. They are optional: leave them blank and the node is a
        # plain code cell. Fill in Target and you can leave the code empty.
        params=(
            {"key": "target", "label": "Target column", "type": "column",
             "help": "Leave the code cell empty to just train on this target."},
            {"key": "kind", "label": "Model", "type": "select",
             "options": ["auto", "rf_classifier", "rf_regressor", "logistic", "linear"],
             "default": "auto"},
            {"key": "test_size", "label": "Test size", "type": "number",
             "default": 0.2, "help": "Hold-out fraction used for the metrics."},
            {"key": "show_metrics", "label": "Print metrics to the log",
             "type": "boolean", "default": True},
        ),
    ))

    # The isolated twin. Declared separately so users can choose: in-process
    # (fast, shares the core environment) or isolated (safe for conflicting
    # dependencies). `requires` is empty because nothing is imported in-process.
    api.register_engine(api.EngineSpec(
        name="sklearn_isolated",
        label="scikit-learn (isolated)",
        description="Runs in its own venv — core env untouched",
        run=make_run_isolated(api),
        input_mode="pandas",
        output_mode="arrow",     # the runner hands back an Arrow table
        language="python",
        tier="free",
        hint=HINT,
        params=(
            {"key": "venv", "label": "Plugin environment", "type": "string",
             "default": "sklearn",
             "help": "Folder name under SFS_PLUGIN_VENVS_DIR, or an absolute path."},
            {"key": "target", "label": "Target column", "type": "column",
             "help": "Leave the code cell empty to just train on this target."},
            {"key": "kind", "label": "Model", "type": "select",
             "options": ["auto", "rf_classifier", "rf_regressor", "logistic", "linear"],
             "default": "auto"},
            {"key": "test_size", "label": "Test size", "type": "number", "default": 0.2},
            {"key": "show_metrics", "label": "Print metrics to the log",
             "type": "boolean", "default": True},
        ),
    ))
