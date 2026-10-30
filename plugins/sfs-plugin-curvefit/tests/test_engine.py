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
