"""Model presets — data, not code.

Adding a preset means adding an entry here. Each entry has:

    id          stable value saved in node data (never rename)
    label       shown in the Model dropdown
    group       dropdown group (by field)
    expression  the model, written in the independent variable `variable`
    variable    independent variable name used in `expression`
    lmfit       optional lmfit built-in model class (and kwargs) to fit with;
                its own `guess()` then supplies starting values
    guess       starting values for expression presets: each value is an
                expression evaluated against the data (see _guess_namespace in
                fit.py: x, y, np, linfit, x_at, dominant_freq, …). A guess that
                fails falls back to 1.
    guess_positive  lmfit's guess takes logs: guess from points with x, y > 0
    free        lmfit parameters that are tied by default but should be fitted
    linear      True when the model is linear in its parameters (exact solution;
                expression presets are checked automatically)

For lmfit built-ins, `expression` is the same function written out, used for
display and by the Evaluate engine. Parameter names match lmfit's.
"""
from __future__ import annotations

R_GAS = 8.314462618  # J/(mol·K)

PRESETS: list[dict] = [
    # ── General ──────────────────────────────────────────────────────────────
    {"id": "linear", "label": "Linear", "group": "General",
     "expression": "slope*x + intercept", "variable": "x",
     "lmfit": ("LinearModel", {}), "linear": True},
    *[
        {"id": f"poly{d}", "label": f"Polynomial (degree {d})", "group": "General",
         "expression": " + ".join(["c0"] + [f"c{i}*x" if i == 1 else f"c{i}*x**{i}" for i in range(1, d + 1)]),
         "variable": "x", "lmfit": ("PolynomialModel", {"degree": d}), "linear": True}
        for d in (2, 3, 4, 5)
    ],
    {"id": "exp_decay", "label": "Exponential decay", "group": "General",
     "expression": "amplitude*exp(-x/decay)", "variable": "x",
     "lmfit": ("ExponentialModel", {}), "guess_positive": True},
    {"id": "exp_decay_offset", "label": "Exponential decay + offset", "group": "General",
     "expression": "amplitude*exp(-x/decay) + c", "variable": "x",
     # Background ≈ the lowest reading; the rest decays (log of the excess).
     "guess": {"c": "min(y)", "decay": "-1/linfit(x, log(y - min(y)))[0]",
               "amplitude": "exp(linfit(x, log(y - min(y)))[1])"}},
    {"id": "exp_growth", "label": "Exponential growth", "group": "General",
     "expression": "A*exp(k*x)", "variable": "x",
     "guess": {"k": "linfit(x, log(y))[0]", "A": "exp(linfit(x, log(y))[1])"}},
    {"id": "power_law", "label": "Power law", "group": "General",
     "expression": "amplitude*x**exponent", "variable": "x",
     "lmfit": ("PowerLawModel", {}), "guess_positive": True},
    {"id": "logistic", "label": "Logistic", "group": "General",
     "expression": "L/(1 + exp(-k*(x - x0)))", "variable": "x",
     "guess": {"L": "max(y)", "x0": "x_at(max(y)/2)", "k": "4/ptp(x)"}},

    # ── Physics ──────────────────────────────────────────────────────────────
    {"id": "gaussian", "label": "Gaussian", "group": "Physics",
     "expression": "amplitude/(sigma*sqrt(2*pi))*exp(-(x - center)**2/(2*sigma**2))",
     "variable": "x", "lmfit": ("GaussianModel", {})},
    {"id": "lorentzian", "label": "Lorentzian", "group": "Physics",
     "expression": "amplitude/pi*sigma/((x - center)**2 + sigma**2)",
     "variable": "x", "lmfit": ("LorentzianModel", {})},
    {"id": "voigt", "label": "Voigt", "group": "Physics",
     # The Faddeeva function has no closed form in the whitelist; Evaluate uses
     # lmfit's VoigtModel for this preset rather than the expression.
     "expression": "voigt(x; amplitude, center, sigma, gamma)",
     # lmfit ties gamma to sigma by default; a lab Voigt fits both widths.
     "variable": "x", "lmfit": ("VoigtModel", {}), "free": ["gamma"], "evaluable": False},
    {"id": "damped_oscillation", "label": "Damped oscillation", "group": "Physics",
     "expression": "A*exp(-t/tau)*cos(2*pi*f*t + phi) + C", "variable": "t",
     "guess": {"C": "mean(y)", "A": "max(abs(y - mean(y)))", "f": "dominant_freq(x, y)",
               "tau": "ptp(x)/2", "phi": "0"}},

    # ── Chemistry ────────────────────────────────────────────────────────────
    {"id": "arrhenius", "label": "Arrhenius", "group": "Chemistry",
     "expression": f"A*exp(-Ea/({R_GAS}*T))", "variable": "T",
     # Linearised fit of ln k against 1/T gives both starting values.
     "guess": {"Ea": f"-linfit(1/x, log(y))[0]*{R_GAS}", "A": "exp(linfit(1/x, log(y))[1])"}},
    {"id": "michaelis_menten", "label": "Michaelis–Menten", "group": "Chemistry",
     "expression": "Vmax*S/(Km + S)", "variable": "S",
     "guess": {"Vmax": "max(y)", "Km": "x_at(max(y)/2)"}},

    # ── Biology ──────────────────────────────────────────────────────────────
    {"id": "hill", "label": "Hill equation", "group": "Biology",
     "expression": "Vmax*x**n/(K**n + x**n)", "variable": "x",
     "guess": {"Vmax": "max(y)", "K": "x_at(max(y)/2)", "n": "1"}},
    {"id": "logistic_growth", "label": "Logistic growth", "group": "Biology",
     "expression": "K/(1 + ((K - N0)/N0)*exp(-r*t))", "variable": "t",
     "guess": {"K": "max(y)", "N0": "y[argmin(x)]", "r": "4/ptp(x)"}},
]

CUSTOM = "custom"
BY_ID: dict[str, dict] = {p["id"]: p for p in PRESETS}


def select_options() -> list[dict]:
    """Options for the Model dropdown, grouped by field, custom last."""
    return [{"value": p["id"], "label": p["label"], "group": p["group"]} for p in PRESETS] + [
        {"value": CUSTOM, "label": "Custom expression…", "group": "Custom"}
    ]
