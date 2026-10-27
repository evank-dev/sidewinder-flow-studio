"""Explore node (explore_out): caches its input frame as an Explore source and
publishes nothing to the report viewer; the Report node still publishes."""
import asyncio

import pytest

from app.core import frame_cache, report_store
from app.core.config import settings
from app.engine import executor
from app.explore import sources


@pytest.fixture
def run_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path / "frames"))
    monkeypatch.setattr(settings, "REPORTS_DIR", str(tmp_path / "reports"))
    events = []

    async def broadcast(_flow_id, msg):
        events.append(msg)
    monkeypatch.setattr(executor.ws_manager, "broadcast", broadcast)

    def run(sink_type):
        flow = {"id": "f1", "nodes": [
            {"id": "t", "type": "trigger", "data": {"label": "Start"}},
            {"id": "p", "type": "processor", "data": {"label": "Numbers", "engine": "duckdb",
                                                      "code": "SELECT i AS x FROM range(5) t(i)"}},
            {"id": "s", "type": sink_type, "data": {"label": "Sink", "report_name": "sink_report"}}],
            "edges": [{"id": "e1", "source": "t", "target": "p"}, {"id": "e2", "source": "p", "target": "s"}]}
        results = asyncio.run(executor.execute_flow("proj1", flow, {}, {}))
        return {r["node_id"]: r for r in results}, events
    return run


def _published(tmp_path):
    db = tmp_path / "reports" / "reports.duckdb"
    if not db.exists():
        return []
    import duckdb
    with duckdb.connect(str(db), read_only=True) as con:
        return [r[0] for r in con.execute("SELECT name FROM _reports").fetchall()]


def test_explore_node_caches_frame_and_publishes_nothing(run_flow, tmp_path):
    results, events = run_flow("explore_out")
    assert results["s"]["status"] == "ok" and results["s"]["rows_out"] == 5
    assert frame_cache.load_frame("proj1", "s")["x"].tolist() == [0, 1, 2, 3, 4]
    ready = [e for e in events if e.get("node_id") == "s" and e["type"].endswith("_ready")]
    assert [e["type"] for e in ready] == ["explore_ready"] and ready[0]["rows"] == 5
    assert _published(tmp_path) == []


def test_report_node_still_publishes(run_flow, tmp_path):
    results, events = run_flow("report_out")
    assert results["s"]["status"] == "ok"
    assert any(e["type"] == "report_ready" and e["kind"] == "dashboard" for e in events)
    assert _published(tmp_path) == ["sink_report"]


def test_unrun_node_says_run_the_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path / "frames"))
    with pytest.raises(FileNotFoundError, match="Run the flow"):
        sources.cached_schema("frame", project_id="proj1", node_id="never_run")
