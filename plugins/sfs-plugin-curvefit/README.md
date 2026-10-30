# sfs-plugin-curvefit

Curve fitting for Sidewinder Flow Studio: load measurements, fit a model, get
the parameters with their uncertainties, without writing code. Built on
[lmfit](https://lmfit.github.io/lmfit-py/).

**Status: in development.** The **Curve fit** engine works; Evaluate, the fit
chart template, View as Python and examples are coming.

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
| General | linear, polynomial (degree 2–5), exponential decay, exponential growth, power law, logistic |
| Physics | Gaussian, Lorentzian, Voigt, damped oscillation |
| Chemistry | Arrhenius, Michaelis–Menten |
| Biology | Hill equation, logistic growth |
| Custom | any expression, e.g. `A*exp(-t/tau) + C` |

The output is one table with columns `kind, name, value, stderr, text`:
a `parameter` row per fitted parameter, `statistic` rows (`chi2`, `redchi`,
`r_squared`, `n_points`) and `model` rows (`expression`, `variable`, `preset`).

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
  form, with `df`, `lmfit` and `np` available.

## Adding a preset

Presets are data in `sfs_plugin_curvefit/presets.py`: an id (never renamed),
label, group, expression and variable, plus either an lmfit built-in model or
starting-value formulas. No other code changes.

## Tests

```bash
pytest plugins/sfs-plugin-curvefit/tests
```
