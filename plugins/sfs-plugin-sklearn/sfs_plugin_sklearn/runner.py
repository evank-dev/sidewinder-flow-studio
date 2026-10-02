"""
Isolated runner — executed by SFS inside this plugin's own virtual environment.

SFS never imports this file. It runs it as:

    <venv>/bin/python runner.py <job>/request.json

so every import below resolves against the *plugin's* pinned dependencies, not
SFS's. That is the whole point: scikit-learn (or PyCaret, statsmodels, …) can
pin whatever it likes without touching the ETL core.

Contract (see backend/app/engine/runtime.py):
  reads   request.json  → {inputs[], output, params, code, meta}
  writes  output.arrow
  prints  one JSON line → {"ok": true, "rows": N, "log": "..."}
          or            → {"ok": false, "error": "..."}
Anything else printed is captured and shown as node logs.
"""
import json
import sys
import traceback


def main(request_path: str) -> int:
    try:
        req = json.loads(open(request_path).read())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"bad request file: {exc}"}))
        return 1

    try:
        import pyarrow as pa
        import pyarrow.ipc as ipc
        import pandas as pd

        inputs = req.get("inputs") or []
        if not inputs:
            print(json.dumps({"ok": False, "error": "no input frame supplied"}))
            return 1

        with ipc.open_file(inputs[0]) as r:
            df = r.read_all().to_pandas()

        params = req.get("params") or {}
        code = req.get("code") or ""

        # ── the actual work, using this venv's scikit-learn ──────────────────
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.linear_model import LinearRegression, LogisticRegression
        from sklearn.metrics import (accuracy_score, f1_score, r2_score,
                                     mean_absolute_error)
        import sklearn

        MODELS = {
            "rf_classifier": RandomForestClassifier,
            "rf_regressor": RandomForestRegressor,
            "logistic": LogisticRegression,
            "linear": LinearRegression,
        }

        def quick_model(frame, target, features=None, kind=None,
                        test_size=0.2, random_state=42, **kw):
            if target not in frame.columns:
                raise ValueError(
                    f"target column '{target}' not in frame. Columns: {list(frame.columns)}")
            y = frame[target]
            X = frame[features] if features else frame.drop(columns=[target])
            X = X.select_dtypes(include="number")
            if X.empty:
                raise ValueError("no numeric feature columns available")
            k = kind
            if k in (None, "", "auto"):
                is_clf = (not pd.api.types.is_numeric_dtype(y)) or y.nunique() <= 20
                k = "rf_classifier" if is_clf else "rf_regressor"
            if k not in MODELS:
                raise ValueError(f"unknown model '{k}'. Options: {list(MODELS)}")
            Xtr, Xte, ytr, yte = train_test_split(
                X, y, test_size=test_size, random_state=random_state)
            model = MODELS[k](**kw).fit(Xtr, ytr)
            pte = model.predict(Xte)
            if k in ("rf_classifier", "logistic"):
                m = {"model": k,
                     "accuracy": round(float(accuracy_score(yte, pte)), 4),
                     "f1_weighted": round(float(f1_score(yte, pte, average="weighted")), 4)}
            else:
                m = {"model": k,
                     "r2": round(float(r2_score(yte, pte)), 4),
                     "mae": round(float(mean_absolute_error(yte, pte)), 4)}
            m.update(n_train=int(len(Xtr)), n_test=int(len(Xte)),
                     features=list(X.columns))
            out = frame.copy()
            out["prediction"] = model.predict(X)
            return out, m

        metrics = None
        if code.strip():
            # Custom code path: the user's code runs HERE, in the isolated
            # interpreter, with the heavy library available.
            scope = {"df": df, "pd": pd, "sklearn": sklearn,
                     "quick_model": quick_model, "train_test_split": train_test_split,
                     **MODELS}
            if params.get("target"):
                scope["TARGET"] = params["target"]
            exec(code, scope)  # noqa: S102
            result = scope.get("df")
            if result is None:
                raise ValueError("node code must leave a DataFrame in `df`")
            df = result
        else:
            target = params.get("target")
            if not target:
                raise ValueError(
                    "set a Target column (or write code) for the isolated scikit-learn engine")
            df, metrics = quick_model(
                df, target=target,
                kind=params.get("kind"),
                test_size=float(params.get("test_size") or 0.2),
            )

        if metrics and params.get("show_metrics", True):
            print("metrics:", json.dumps(metrics))
        print(f"sklearn {sklearn.__version__} (isolated: {sys.executable})")

        table = pa.Table.from_pandas(df, preserve_index=False)
        with ipc.new_file(req["output"], table.schema) as w:
            w.write_table(table)

        print(json.dumps({"ok": True, "rows": int(table.num_rows)}))
        return 0

    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False,
                          "error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc()[-1500:]}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
