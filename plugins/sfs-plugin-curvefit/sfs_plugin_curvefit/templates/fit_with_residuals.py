# Fit with residuals — the data with error bars, the fitted curve over it, and
# the residuals (data − model) in a panel beneath.
#
# Connect to this Chart node:
#   • the measurements
#   • an Evaluate model node in Range mode (the smooth curve)
#   • optionally the Curve fit node: its parameters are printed on the plot and
#     the residuals are computed exactly at each data point
# The inputs are told apart by their columns, so the order doesn't matter.

# ── settings (leave empty to take them from the fit) ──────────────────────────
X = ""            # x column
Y = ""            # measured column
Y_ERR = ""        # y uncertainty column (optional)
TITLE = ""
X_LABEL = ""      # axis labels; default to the column names
Y_LABEL = ""

import matplotlib.pyplot as plt
import numpy as np


def is_parameter_table(f):
    return {"kind", "name", "value", "stderr"} <= set(f.columns)


# ── find the inputs by their columns ──────────────────────────────────────────
frames = [f for f in dfs if f is not None and len(f.columns) > 0]
tables = [f for f in frames if is_parameter_table(f)]
curves = [f for f in frames if not is_parameter_table(f)
          and len(f.columns) == 2 and "value" in f.columns]
data = [f for f in frames if not is_parameter_table(f) and not any(f is c for c in curves)]
if not curves:
    raise ValueError("Connect an Evaluate model node in Range mode: it draws the fitted curve")
if len(data) != 1:
    raise ValueError(f"Connect exactly one measurements node ({len(data)} found)")
curve, data = curves[0], data[0]
table = tables[0] if tables else None

model = {}
if table is not None:
    rows = table[table["kind"] == "model"]
    model = {n: t for n, t in zip(rows["name"], rows["text"]) if isinstance(t, str) and t}
X = X or model.get("x_column") or next(c for c in curve.columns if c != "value")
Y = Y or model.get("y_column", "")
if not Y:
    # The one numeric column that isn't x or an uncertainty
    candidates = [c for c in data.select_dtypes("number").columns
                  if c != X and not str(c).endswith("_err") and c != "value"]
    if len(candidates) != 1:
        raise ValueError(f"Set Y at the top of the chart code (one of: {', '.join(map(str, candidates))})")
    Y = candidates[0]
Y_ERR = Y_ERR or model.get("y_err_column") or (f"{Y}_err" if f"{Y}_err" in data.columns else "")
X_ERR = f"{X}_err" if f"{X}_err" in data.columns else ""
for col in (X, Y, Y_ERR):
    if col and col not in data.columns:
        raise ValueError(f"Column '{col}' is not in the measurements. Columns: {', '.join(map(str, data.columns))}")

data = data.sort_values(X)
x, y = data[X].to_numpy(float), data[Y].to_numpy(float)
y_err = data[Y_ERR].to_numpy(float) if Y_ERR else None
x_err = data[X_ERR].to_numpy(float) if X_ERR else None
curve = curve.sort_values(curve.columns[0])

# ── the model at each data point ──────────────────────────────────────────────
if table is not None:
    # Exact: evaluate the fitted model at the measured x values
    from sfs_plugin_curvefit.evaluate import evaluate_columns
    y_model = evaluate_columns(data[[X]], table, x=X)["value"].to_numpy(float)
else:
    # Without the fit, read the model off the curve (connect the Curve fit
    # node for exact residuals)
    y_model = np.interp(x, curve.iloc[:, 0], curve["value"], left=np.nan, right=np.nan)
    if np.isnan(y_model).any():
        print("Note: some data lie outside the curve's range; widen Start/Stop in Evaluate model")
residuals = y - y_model

# ── plot ──────────────────────────────────────────────────────────────────────
fig, (ax, ax_res) = plt.subplots(2, 1, sharex=True, figsize=(8, 6),
                                 gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05})
ax.errorbar(x, y, yerr=y_err, xerr=x_err, fmt="o", ms=4, capsize=2,
            color="#1f77b4", ecolor="#7aa6d1", label="data")
ax.plot(curve.iloc[:, 0], curve["value"], "-", lw=2, color="#d62728", label="fit")
ax.set_ylabel(Y_LABEL or Y)
ax.legend(loc="best", frameon=False)
if TITLE:
    ax.set_title(TITLE)

if table is not None:
    # Parameters as value ± error, rounded to the error's significant digits
    from uncertainties import ufloat
    lines = []
    for _, p in table[table["kind"] == "parameter"].iterrows():
        if np.isfinite(p["stderr"]) and p["stderr"] > 0:
            lines.append(f"{p['name']} = {ufloat(p['value'], p['stderr']):.2uP}")
        else:
            lines.append(f"{p['name']} = {p['value']:.4g}")
    stats = dict(zip(table.loc[table["kind"] == "statistic", "name"],
                     table.loc[table["kind"] == "statistic", "value"]))
    if "redchi" in stats:
        lines.append(f"χ²/ν = {stats['redchi']:.3g}")
    if "expression" in model:
        lines.insert(0, model["expression"])
    ax.text(0.98, 0.97, "\n".join(lines), transform=ax.transAxes, ha="right", va="top",
            fontsize=9, family="monospace",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8, "edgecolor": "#cccccc"})

ax_res.axhline(0, color="#d62728", lw=1)
ax_res.errorbar(x, residuals, yerr=y_err, fmt="o", ms=3, capsize=2,
                color="#1f77b4", ecolor="#7aa6d1")
ax_res.set_ylabel("residual")
ax_res.set_xlabel(X_LABEL or X)
fig.align_ylabels([ax, ax_res])
