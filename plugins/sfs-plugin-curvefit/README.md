# sfs-plugin-curvefit

Curve fitting for Sidewinder Flow Studio: load measurements, fit a model, get
the parameters with their uncertainties, without writing code. Built on
[lmfit](https://lmfit.github.io/lmfit-py/).

**Status: in development.** The **Curve fit** and **Evaluate model** engines
and the **Fit with residuals** chart template work; View as Python and
examples are coming.

## Install

```bash
pip install -e plugins/sfs-plugin-curvefit
```

The Docker images include it by default.

## Curve fit (`curvefit_fit`)

Pick a processor's engine **Curve fit**, then the x and y columns, optionally a
y-error column, and a model:

| Group | Models |
|---|---|
| General | linear, polynomial (degree 2–5), exponential decay, exponential decay + offset, exponential growth, power law, logistic |
| Physics | Gaussian, Lorentzian, Voigt, damped oscillation |
| Chemistry | Arrhenius, Michaelis–Menten |
| Biology | Hill equation, logistic growth |
| Custom | any expression, e.g. `A*exp(-t/tau) + C` |

The output is one table with columns `kind, name, value, stderr, text`:
a `parameter` row per fitted parameter, `statistic` rows (`chi2`, `redchi`,
`r_squared`, `n_points`) and `model` rows (`expression`, `variable`, `preset`,
`x_column`, `y_column`, `y_err_column`).

- **Uncertainties:** with a y-error column, points are weighted by 1/σ and the
  parameter errors are absolute (not rescaled by the fit quality). Without one,
  errors are scaled by the reduced χ².
- **Starting values:** presets guess automatically; give your own as
  `A=1, tau=2` when a fit fails. A nonlinear fit that explains less than 10 %
  of the variance is reported as a failed fit (a wrong local minimum), with
  the parameters to guess named.
- **Custom expressions** may use `exp log sqrt sin cos tan sinh cosh tanh abs`,
  the constants `pi` and `e`, the variable, and any parameter names; `^` means
  power. This checks the input, it is not a sandbox: like all SFS node code,
  models run with the backend's privileges.
- **Take over in code:** anything in the node's code cell runs instead of the
  form, with `df`, `lmfit` and `np` available (in both engines).

## Evaluate model (`curvefit_eval`)

Turns parameters back into values. Connect a Curve fit node and leave Model on
**From the connected fit**, or pick a model and type its parameters
(`A=2, tau=5`).

- **Range** mode needs no data: the model over Start…Stop at Points steps.
  Output `<x>, value`, where `<x>` is the fit's x column (so the curve and the
  data share an axis), else the variable name.
- **Columns** mode evaluates over the rows of a connected data node and adds a
  `value` column (rename it with Output column). The variable is read from the
  x column field, else the fit's x column, else the column named like the
  variable. Any other name in the expression that is not a parameter is read
  from the column of that name, so `m*g*h` with `g=9.81` works on columns
  `m` and `h`.
- **Uncertainty propagation:** a `<name>_err` column next to any input column is
  propagated to `value_err` (first order, inputs independent, using
  [uncertainties](https://uncertainties.readthedocs.io/)).
- The parameter table is recognised by its columns, so it doesn't matter in
  which order the fit and the data are connected.

**Limitations (v1):** parameter uncertainties are not propagated, and range mode
gives values only, no confidence band. Both need the parameter covariance
matrix, which the parameter table doesn't carry. The Voigt model is evaluated
by lmfit and supports no propagation.

## Fit with residuals (chart template)

In a Chart node, pick **Start from a template → Fit with residuals**. Connect
the measurements, an Evaluate model node in Range mode (the curve) and,
optionally, the Curve fit node. The chart shows the data with error bars, the
fitted curve, a box with the model and parameters (value ± error, rounded to
the error) and χ²/ν, and the residuals beneath.

With the Curve fit connected, the x, y and y-error columns come from the fit
and the residuals are exact; without it they are read off the curve. The
settings at the top of the code (columns, title, axis labels) can be edited,
and so can everything else: the code is yours once inserted.

## Adding a preset

Presets are data in `sfs_plugin_curvefit/presets.py`: an id (never renamed),
label, group, expression and variable, plus either an lmfit built-in model or
starting-value formulas. No other code changes.

## Tests

```bash
pytest plugins/sfs-plugin-curvefit/tests
```
