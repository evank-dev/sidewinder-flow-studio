"""The plugin inside SFS: registration through the entry point, and a real flow
run through the executor (measurements → Curve fit)."""
import asyncio

import numpy as np
import pytest

pytest.importorskip("app.engine.registry", reason="needs the SFS backend installed")

from app.core import frame_cache                 # noqa: E402
from app.core.config import settings             # noqa: E402
from app.engine import executor, registry        # noqa: E402


def test_registered_through_the_entry_point():
    registry.load_plugins()
    loaded = {p["name"]: p for p in registry.loaded_plugins()}
    assert loaded["curvefit"]["loaded"], loaded["curvefit"]["error"]
    eng = {e["name"]: e for e in registry.list_engines()}["curvefit_fit"]
    assert eng["label"] == "Curve fit" and eng["available"] and eng["source"].startswith("plugin:")
    model = next(p for p in eng["params"] if p["key"] == "model")
    groups = [o["group"] for o in model["options"]]
    assert groups[0] == "General" and groups[-1] == "Custom"
    assert {"Physics", "Chemistry", "Biology"} <= set(groups)


@pytest.fixture
def run_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path / "frames"))

    async def broadcast(_flow_id, _msg):
        pass
    monkeypatch.setattr(executor.ws_manager, "broadcast", broadcast)
    registry.load_plugins()

    def run(fit_data):
        data_code = ("import numpy as np\n"
                     "t = np.linspace(0, 20, 60)\n"
                     "df = pd.DataFrame({'t': t, 'counts': 4*np.exp(-t/6) + 1, 'err': 0.05})\n")
        flow = {"id": "f1", "nodes": [
            {"id": "start", "type": "trigger", "data": {"label": "Start"}},
            {"id": "data", "type": "processor", "data": {"label": "Measurements", "engine": "pandas", "code": data_code}},
            {"id": "fit", "type": "processor", "data": {"label": "Fit", "engine": "curvefit_fit", "code": "", **fit_data}}],
            "edges": [{"id": "e1", "source": "start", "target": "data"}, {"id": "e2", "source": "data", "target": "fit"}]}
        results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
        return results["fit"]
    return run


def test_fit_node_in_a_flow(run_flow):
    r = run_flow({"x": "t", "y": "counts", "y_err": "err", "model": "custom",
                  "expression": "A*exp(-t/tau) + C", "variable": "t", "initial": "A=1, tau=3, C=0"})
    assert r["status"] == "ok", r.get("detail")
    table = frame_cache.load_frame("proj1", "fit")
    p = table[table.kind == "parameter"].set_index("name").value
    assert p["A"] == pytest.approx(4) and p["tau"] == pytest.approx(6) and p["C"] == pytest.approx(1)
    assert list(table.columns) == ["kind", "name", "value", "stderr", "text"]


def test_fit_node_error_reaches_the_node(run_flow):
    r = run_flow({"x": "t", "y": "nope", "model": "linear"})
    assert r["status"] == "error" and "Column 'nope'" in r["detail"]


def test_code_cell_takes_over(run_flow):
    code = ("model = lmfit.models.LinearModel()\n"
            "res = model.fit(df['counts'], model.guess(df['counts'], x=df['t']), x=df['t'])\n"
            "df = pd.DataFrame({'name': list(res.params), 'value': [p.value for p in res.params.values()]})\n")
    flow_fit = {"x": "t", "y": "counts", "model": "linear"}
    r = run_flow(flow_fit | {"code": code})
    assert r["status"] == "ok", r.get("detail")
    assert list(frame_cache.load_frame("proj1", "fit").columns) == ["name", "value"]


def _chain(eval_data, data_id="data", fit_id="fit"):
    """Start → measurements → Curve fit → Evaluate, with measurements also wired
    into Evaluate. Node ids decide input order, so tests swap them."""
    data_code = ("import numpy as np\n"
                 "t = np.linspace(0, 20, 60)\n"
                 "df = pd.DataFrame({'t': t, 'counts': 4*np.exp(-t/6) + 1, 't_err': 0.1})\n")
    fit_data = {"x": "t", "y": "counts", "model": "exp_decay_offset"}
    return {"id": "f1", "nodes": [
        {"id": "start", "type": "trigger", "data": {"label": "Start"}},
        {"id": data_id, "type": "processor", "data": {"label": "Measurements", "engine": "pandas", "code": data_code}},
        {"id": fit_id, "type": "processor", "data": {"label": "Fit", "engine": "curvefit_fit", "code": "", **fit_data}},
        {"id": "ev", "type": "processor", "data": {"label": "Evaluate", "engine": "curvefit_eval", "code": "", **eval_data}}],
        "edges": [{"id": "e1", "source": "start", "target": data_id},
                  {"id": "e2", "source": data_id, "target": fit_id},
                  {"id": "e3", "source": fit_id, "target": "ev"},
                  {"id": "e4", "source": data_id, "target": "ev"}]}


@pytest.mark.parametrize("ids", [("data", "fit"), ("zdata", "afit")])
def test_fit_then_evaluate_columns_in_either_input_order(run_flow, ids):
    flow = _chain({"mode": "columns", "output": "fit"}, *ids)
    results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
    assert results["ev"]["status"] == "ok", results["ev"].get("detail")
    out = frame_cache.load_frame("proj1", "ev")
    assert list(out.columns) == ["t", "counts", "t_err", "fit", "fit_err"]
    np.testing.assert_allclose(out["fit"], out["counts"], rtol=1e-6)
    # σ_f = |df/dt| σ_t, with df/dt = -A/τ e^(-t/τ)
    expected = 4 / 6 * np.exp(-out["t"] / 6) * 0.1
    np.testing.assert_allclose(out["fit_err"], expected, rtol=1e-5)


def test_fit_then_evaluate_range(run_flow):
    flow = _chain({"mode": "range", "start": 0, "stop": 10, "points": 11})
    flow["edges"] = [e for e in flow["edges"] if e["id"] != "e4"]
    results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
    assert results["ev"]["status"] == "ok", results["ev"].get("detail")
    out = frame_cache.load_frame("proj1", "ev")
    # Named after the fit's x column, so curve and data share an axis.
    assert list(out.columns) == ["t", "value"] and len(out) == 11
    np.testing.assert_allclose(out["value"], 4 * np.exp(-out["t"] / 6) + 1, rtol=1e-6)


def test_evaluate_range_with_no_upstream_data(run_flow):
    flow = {"id": "f1", "nodes": [
        {"id": "start", "type": "trigger", "data": {"label": "Start"}},
        {"id": "ev", "type": "processor", "data": {"label": "Evaluate", "engine": "curvefit_eval", "code": "",
                                                    "mode": "range", "model": "gaussian",
                                                    "parameters": "amplitude=1, center=0, sigma=1",
                                                    "start": -3, "stop": 3, "points": 7}}],
        "edges": [{"id": "e1", "source": "start", "target": "ev"}]}
    results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
    assert results["ev"]["status"] == "ok", results["ev"].get("detail")
    out = frame_cache.load_frame("proj1", "ev")
    assert out["value"][3] == pytest.approx(1 / np.sqrt(2 * np.pi))


def test_evaluate_is_registered():
    registry.load_plugins()
    eng = {e["name"]: e for e in registry.list_engines()}["curvefit_eval"]
    assert eng["label"] == "Evaluate model" and eng["available"]
    model = next(p for p in eng["params"] if p["key"] == "model")
    assert model["default"] == "from_fit" and model["options"][0]["value"] == "from_fit"


def test_fit_plot_in_a_flow(run_flow, monkeypatch):
    """measurements → fit → evaluate(range) → Chart (Fit with residuals), with
    the measurements and the fit also wired into the Chart."""
    registry.load_plugins()
    code = next(t["code"] for t in registry.list_templates("chart") if t["name"] == "Fit with residuals")
    messages = []

    async def broadcast(_flow_id, msg):
        messages.append(msg)
    monkeypatch.setattr(executor.ws_manager, "broadcast", broadcast)
    flow = _chain({"mode": "range", "start": 0, "stop": 20, "points": 100})
    flow["edges"] = [e for e in flow["edges"] if e["id"] != "e4"]
    flow["nodes"].append({"id": "plot", "type": "chart_out", "data": {"label": "Fit plot", "code": code}})
    flow["edges"] += [{"id": f"p{i}", "source": s, "target": "plot"} for i, s in enumerate(("data", "fit", "ev"))]
    results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
    assert results["plot"]["status"] == "ok", results["plot"].get("detail")
    chart = next(m for m in messages if m.get("type") == "chart_ready")
    assert chart["chart_type"] == "png" and len(chart["payload"]) > 10_000


def test_template_is_registered():
    registry.load_plugins()
    t = next(t for t in registry.list_templates("chart") if t["name"] == "Fit with residuals")
    assert t["source"] == "plugin:curvefit" and "is_parameter_table" in t["code"]


def test_convert_to_code_node_gives_the_same_frames(run_flow):
    """Run fit → evaluate, convert both nodes to pandas with their generated
    code (as the Convert button does), run again: identical outputs."""
    import pandas as pd

    flow = _chain({"mode": "columns", "output": "fit"}, "data", "fit")
    asyncio.run(executor.execute_flow("proj1", flow, {}, {}))
    before = {n: frame_cache.load_frame("proj1", n) for n in ("fit", "ev")}

    registry.load_plugins()
    for node in flow["nodes"]:
        d = node["data"]
        if d.get("engine", "").startswith("curvefit"):
            spec = registry.ENGINES[d["engine"]]
            parents = [e["source"] for e in flow["edges"] if e["target"] == node["id"]]
            inputs = [frame_cache.load_frame("proj1", p) for p in parents]
            d.update(engine="pandas", code=spec.to_code(spec.resolve_params(d), inputs))
    results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
    for n in ("fit", "ev"):
        assert results[n]["status"] == "ok", results[n].get("detail")
        pd.testing.assert_frame_equal(frame_cache.load_frame("proj1", n), before[n], rtol=1e-9)


def test_to_code_endpoint(run_flow):
    from fastapi.testclient import TestClient
    from app.core.app_factory import create_app

    flow = _chain({"mode": "range", "start": 0, "stop": 5, "points": 6})
    asyncio.run(executor.execute_flow("proj1", flow, {}, {}))
    client = TestClient(create_app())
    ev = next(n for n in flow["nodes"] if n["id"] == "ev")["data"]
    r = client.post("/api/capabilities/to-code", json={"engine": "curvefit_eval", "node_data": ev,
                                                       "project_id": "proj1", "parent_ids": ["fit", "data"]})
    assert r.status_code == 200 and "np.linspace(0.0, 5.0, 6)" in r.json()["code"]
    r = client.post("/api/capabilities/to-code", json={"engine": "curvefit_eval", "node_data": ev})
    assert r.status_code == 400 and "Run the flow once" in r.json()["detail"]
    r = client.post("/api/capabilities/to-code", json={"engine": "pandas", "node_data": {}})
    assert r.status_code == 404
    caps = {e["name"]: e for e in client.get("/api/capabilities/").json()["engines"]}
    assert caps["curvefit_fit"]["has_to_code"] and not caps["pandas"]["has_to_code"]
