"""Phase 4: the example flows run end to end, and real data are reproduced.

Real-data validation: the radioactive decay counts supplied by the owner are
fitted by the engine and, independently, by scipy.optimize.curve_fit; the two
must agree, and the half-life node must report t½ = τ·ln 2 with its error.
"""
import asyncio
import copy

import numpy as np
import pandas as pd
import pytest

from sfs_plugin_curvefit.examples import EXAMPLES, data_path

pytest.importorskip("app.engine.registry", reason="needs the SFS backend installed")

from app.core import frame_cache                 # noqa: E402
from app.core.config import settings             # noqa: E402
from app.engine import executor, registry        # noqa: E402

FLOWS = {name: flow for name, _, flow in EXAMPLES}


@pytest.fixture
def run_example(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path / "frames"))
    messages = []

    async def broadcast(_flow_id, msg):
        messages.append(msg)
    monkeypatch.setattr(executor.ws_manager, "broadcast", broadcast)
    registry.load_plugins()

    def run(name):
        flow = {"id": "f1", **copy.deepcopy(FLOWS[name])}
        results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
        charts = [m for m in messages if m.get("type") == "chart_ready"]
        return results, charts
    return run


@pytest.mark.parametrize("name", list(FLOWS))
def test_example_runs_end_to_end(run_example, name):
    results, charts = run_example(name)
    executable = [n["id"] for n in FLOWS[name]["nodes"] if n["type"] != "annotation"]
    for node_id in executable:
        assert results[node_id]["status"] == "ok", (node_id, results[node_id].get("detail"))
    assert len(charts) == 1 and charts[0]["chart_type"] == "png"


def test_examples_are_registered():
    registry.load_plugins()
    names = [e["name"] for e in registry.list_examples()]
    assert {n for n, _, _ in EXAMPLES} <= set(names)


def test_sample_data_ship_with_the_package():
    assert list(pd.read_csv(data_path("radioactive_decay.csv")).columns) == ["Time", "Activity"]
    assert list(pd.read_csv(data_path("enzyme_kinetics.csv")).columns) == ["S_mM", "rate", "rate_err"]


# ── real-data validation ──────────────────────────────────────────────────────

def test_real_decay_data_match_an_independent_fit(run_example):
    from scipy.optimize import curve_fit

    results, _ = run_example(next(n for n in FLOWS if "decay" in n.lower()))
    table = frame_cache.load_frame("proj1", "fit")
    p = table[table.kind == "parameter"].set_index("name")

    data = pd.read_csv(data_path("radioactive_decay.csv"))
    t, n = data.Time.to_numpy(float), data.Activity.to_numpy(float)
    popt, pcov = curve_fit(lambda t, a, tau: a * np.exp(-t / tau), t, n, p0=(1000, 40),
                           sigma=np.sqrt(n), absolute_sigma=True)
    perr = np.sqrt(np.diag(pcov))
    np.testing.assert_allclose(p.loc[["amplitude", "decay"], "value"], popt, rtol=1e-5)
    np.testing.assert_allclose(p.loc[["amplitude", "decay"], "stderr"], perr, rtol=1e-3)

    half = frame_cache.load_frame("proj1", "halflife").set_index("quantity")
    assert half.loc["half-life t½", "value"] == pytest.approx(popt[1] * np.log(2), rel=1e-5)
    assert half.loc["half-life t½", "error"] == pytest.approx(perr[1] * np.log(2), rel=1e-3)
    # The values reported to the owner: t½ = 26.4 ± 0.6
    assert round(half.loc["half-life t½", "value"], 1) == 26.4
    assert round(half.loc["half-life t½", "error"], 1) == 0.6


def test_enzyme_example_recovers_its_constants(run_example):
    run_example(next(n for n in FLOWS if "enzyme" in n.lower()))
    p = frame_cache.load_frame("proj1", "fit").query("kind == 'parameter'").set_index("name")
    # Generated with Vmax = 48, Km = 2.6
    for name, true in (("Vmax", 48), ("Km", 2.6)):
        assert abs(p.loc[name, "value"] - true) < 3 * p.loc[name, "stderr"], (name, p.loc[name].to_dict())
