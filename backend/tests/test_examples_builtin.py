"""SFS's own example flows (app/examples) run end to end and are listed."""
import asyncio
import copy

import pytest

from app import examples
from app.core.config import settings
from app.engine import executor, registry


@pytest.fixture
def run_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path / "frames"))
    messages = []

    async def broadcast(_flow_id, msg):
        messages.append(msg)
    monkeypatch.setattr(executor.ws_manager, "broadcast", broadcast)

    def run(flow):
        flow = {"id": "f1", **copy.deepcopy(flow)}
        results = {r["node_id"]: r for r in asyncio.run(executor.execute_flow("proj1", flow, {}, {}))}
        return results, messages
    return run


@pytest.mark.parametrize("name,flow", [(n, f) for n, _, f in examples.EXAMPLES])
def test_example_runs_end_to_end(run_flow, name, flow):
    results, messages = run_flow(flow)
    for node in flow["nodes"]:
        if node["type"] != "annotation":
            r = results[node["id"]]
            assert r["status"] == "ok", (name, node["id"], r.get("detail"))
    assert any(m.get("type") == "chart_ready" for m in messages)


def test_sales_pipeline_cleans_and_summarises(run_flow):
    from app.core.frame_cache import load_frame_head

    run_flow(examples.SALES_PIPELINE)
    clean = load_frame_head("proj1", "clean", 1000)
    assert clean["quantity"].notna().all() and set(clean["region"]) == {"North", "South", "East", "West"}
    top = load_frame_head("proj1", "top", 10)
    assert list(top.columns) == ["product", "revenue", "units"] and len(top) == 5
    assert top["revenue"].is_monotonic_decreasing


def test_builtin_examples_are_listed_first():
    registry.load_plugins()
    names = [e["name"] for e in registry.list_examples()]
    assert names[0] == "Sales pipeline (CSV)"
    assert registry.get_example("Sales pipeline (CSV)")["source"] == "builtin"
