# Curve fitting

Fit a model to measurements, get the parameters with their uncertainties, plot
the fit with its residuals, and see it all as plain Python. Provided by the
`sfs-plugin-curvefit` plugin (included in the Docker images), built on
[lmfit](https://lmfit.github.io/lmfit-py/).

A **model** is a formula with one independent variable and named parameters,
such as `A*exp(-t/tau) + C`. Two engines use it:

- **Curve fit**: data → parameters ± errors
- **Evaluate model**: parameters → values, over a range or over your rows

## Start with an example

Open the project picker and choose one under **Start from an example**:

| Example | What it shows |
|---|---|
| Curve fit · Radioactive decay (physics) | Counts with √N errors → exponential fit → half-life t½ = τ·ln 2 with its error, and the fit plot |
| Curve fit · Enzyme kinetics (biochemistry) | Initial rates with replicate errors → Michaelis–Menten fit → Vmax, Km and the fit plot |

Each creates a new project. Click **Run Flow**, then open the Fit plot node. The
flows read sample data shipped with the plugin. To use your own, edit the first
node, for example `df = pd.read_csv('/data/imports/my_data.csv')`. In Docker,
files must be under the `/data/imports` mount.

The decay example uses real classroom data (activity counted every 10 time
units). Its result is t½ = 26.4 ± 0.6, which the plugin's tests check against an
independent fit with `scipy.optimize.curve_fit`.

## The usual flow

```
measurements ─┬─▶ Curve fit ─┬─▶ Evaluate model (Range) ─┐
              │              └───────────────────────────┤
              └──────────────────────────────────────────┴─▶ Chart: Fit with residuals
```

1. **Measurements**: any node producing a table with an x column, a y column
   and, if you have them, the y uncertainties.
2. **Curve fit**: add a Processor and pick the **Curve fit** engine. Choose the
   x, y and (optional) y error columns and a model.
3. **Evaluate model**: a Processor with the **Evaluate model** engine, connected
   to the fit. Range mode, from Start to Stop, draws the smooth curve.
4. **Chart**: a Chart View node connected to the measurements, the fit and the
   curve. Pick **Start from a template → Fit with residuals**.

The order you connect inputs in never matters: the nodes recognise the fit's
table by its columns.

## Curve fit

**Models**, grouped in the dropdown:

| Group | Models |
|---|---|
| General | linear, polynomial (degree 2–5), exponential decay, exponential decay + offset, exponential growth, power law, logistic |
| Physics | Gaussian, Lorentzian, Voigt, damped oscillation |
| Chemistry | Arrhenius, Michaelis–Menten |
| Biology | Hill equation, logistic growth |
| Custom | any expression, e.g. `A*exp(-t/tau) + C` |

A **custom expression** may use `exp log sqrt sin cos tan sinh cosh tanh abs`,
the constants `pi` and `e`, the variable (set **Variable in the expression**,
e.g. `t`) and any parameter names. `^` means power. Unknown functions are
reported by name.

**The output** is one table, so it can be inspected, charted and passed on:

| kind | name | value | stderr | text |
|---|---|---|---|---|
| parameter | decay | 38.10 | 0.84 | |
| statistic | chi2, redchi, r_squared, n_points | … | | |
| model | expression, variable, preset, x_column, y_column, y_err_column | | | `amplitude*exp(-x/decay)` … |

**Uncertainties.** With a y-error column, points are weighted by 1/σ and the
parameter errors are absolute: they come from your stated uncertainties, not
from the scatter. Then χ²/ν (`redchi`) tells you whether the stated errors and
the scatter agree. Near 1 is consistent; much above 1 means the model or the
errors are wrong; much below 1 means the errors are overestimated. Without a
y-error column, the errors are scaled by the reduced χ², the usual choice when
the uncertainties are unknown.

**Starting values.** Presets estimate them from the data. If a fit fails, the
message names the parameters to guess: type them in **Initial guesses** as
`A=1000, tau=40`. A nonlinear fit that explains less than 10 % of the variance
is reported as failed, because lmfit can report "success" in a wrong local
minimum.

## Evaluate model

Leave **Model** on *From the connected fit*, or pick a model and type the
parameter values (`A=2, tau=5`).

- **Range**: the model from Start to Stop. The x column is named like the fit's
  x column, so the curve and the data share an axis.
- **Columns**: the model at every row of a connected data node, added as a
  `value` column (rename it with **Output column**). The variable is read from
  the **x column** field, else the fit's x column. Any other name in the
  expression is read from a column of that name, so a formula such as `m*g*h`
  with `g=9.81` works on columns `m` and `h`.
- **Error propagation**: in Columns mode, a `<name>_err` column next to an input
  column is propagated (first order, inputs independent) into `value_err`.

**Limitations.** Parameter uncertainties are not propagated, and Range mode gives
no confidence band. Both need the parameter covariance matrix, which the fit
table doesn't carry. The Voigt model is evaluated by lmfit without propagation.

## Fit with residuals

The chart template draws the data with error bars, the fitted curve, a box with
the model, the parameters (value ± error, rounded to the error) and χ²/ν, and
the residuals beneath. Residuals should scatter around zero with no pattern; a
trend means the model is missing something. The settings at the top of the code
(columns, title, axis labels) can be edited. Once inserted, the code is yours.

## View as Python

Both engines have **View as Python** (read-only, with Copy) and **Convert to
code node** (switches the node to pandas with that code). The code is plain
lmfit, NumPy and `uncertainties`, commented step by step, with no dependency on
the plugin, and it produces the same table as the engine. The model function in
it is the exact source the engine runs. Run the flow once before viewing an
Evaluate node, since its model comes from the fit's last result.

To take over completely without converting, type code in the node's code cell:
it runs instead of the form, with `df`, `lmfit` and `np` available.

## Safety

Custom expressions are checked against the list of allowed functions. That is
input validation, not a sandbox: like all SFS node code, models run with the
backend's privileges.
