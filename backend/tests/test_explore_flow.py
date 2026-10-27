"""Explore Phase 3: Explore → flow node, and drill-through to a detail table.

Generated node code is executed (DuckDB SQL in DuckDB, SQL in SQLite, pandas
code with a stand-in get_engine), so these tests check what the node does,
not just what it says.
"""
import json
from types import SimpleNamespace

import duckdb
import pandas as pd
import pyarrow as pa
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import explore as explore_api
from app.core import frame_cache
from app.core.config import settings
from app.core.database import get_db
from app.explore import drill, nodegen
from app.services import project_service

FIELDS = [{"fid": "g", "semanticType": "nominal", "sqlType": "VARCHAR"},
          {"fid": "x", "semanticType": "quantitative", "sqlType": "BIGINT"},
          {"fid": "ts", "semanticType": "temporal", "sqlType": "TIMESTAMP"}]
FILTERED_CHART = {"workflow": [
    {"type": "filter", "filters": [
        {"fid": "g", "rule": {"type": "one of", "value": ["a"]}},
        {"fid": "gw_bin1", "rule": {"type": "range", "value": [0, 5]}}]},
    {"type": "transform", "transform": [{"key": "gw_bin1", "expression": {
        "op": "bin", "as": "gw_bin1", "params": [{"type": "field", "value": "x"}], "num": 10}}]},
    {"type": "view", "query": [{"op": "aggregate", "groupBy": ["g"], "measures": [
        {"field": "x", "agg": "sum", "asFieldKey": "x_sum"}]}]}], "limit": 5}
ROWS = [("a" if i % 2 else "b", i, f"2024-01-{1 + i % 28:02d} 10:00:00") for i in range(40)]


def _strip_sql_comments(code: str) -> str:
    return "\n".join(l for l in code.splitlines() if not l.lstrip().startswith("--"))


@pytest.fixture
def sqlite(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t (g TEXT, x INTEGER, ts TEXT)")
        c.exec_driver_sql("INSERT INTO t VALUES " + ",".join(f"('{g}', {x}, '{ts}')" for g, x, ts in ROWS))
    return eng


# ── node generation ───────────────────────────────────────────────────────────

def test_dataset_keeps_source_filters_drops_chart_parts():
    p, dropped = nodegen.dataset_payload(FILTERED_CHART, FIELDS)
    assert p == {"workflow": [
        {"type": "filter", "filters": [{"fid": "g", "rule": {"type": "one of", "value": ["a"]}}]},
        {"type": "view", "query": [{"op": "raw", "fields": ["g", "x", "ts"]}]}]}
    assert dropped == ["gw_bin1"]


def test_cached_dataset_node_is_duckdb_over_df():
    out = nodegen.make_node("frame", FILTERED_CHART, FIELDS, mode="dataset", label="Load sales",
                            input_hint="connect “Load sales” to this node")
    node = out["node"]
    assert node["engine"] == "duckdb" and node["label"] == "Explore · Load sales"
    assert "-- Input: connect “Load sales” to this node" in node["code"]
    assert out["notes"] == ["Filters on computed fields were left out: gw_bin1"]
    con = duckdb.connect()
    con.register("df", pa.table({"g": [r[0] for r in ROWS], "x": [r[1] for r in ROWS],
                                 "ts": pd.to_datetime([r[2] for r in ROWS])}))
    got = con.execute(node["code"]).fetchall()
    assert len(got) == 20 and {r[0] for r in got} == {"a"}          # every column, only g = 'a'


def test_cached_chart_node_keeps_aggregation_drops_limit():
    node = nodegen.make_node("persist", FILTERED_CHART, FIELDS, mode="chart", label="sales")["node"]
    assert "LIMIT" not in node["code"].upper().split("FROM")[-1]
    con = duckdb.connect()
    con.register("df", pa.table({"g": [r[0] for r in ROWS], "x": [r[1] for r in ROWS]}))
    fields = FIELDS[:2]
    node = nodegen.make_node("persist", {"workflow": FILTERED_CHART["workflow"][2:]}, fields,
                             mode="chart", label="sales")["node"]
    assert dict(con.execute(node["code"]).fetchall()) == {"a": sum(range(1, 40, 2)), "b": sum(range(0, 40, 2))}


def test_live_sql_node_runs_in_the_database(sqlite):
    out = nodegen.make_node("table", FILTERED_CHART, FIELDS[:2], mode="dataset", label="t", engine="sql",
                            dialect="sqlite", connection="warehouse", table="t")
    node = out["node"]
    assert node["engine"] == "sql" and node["target_connection"] == "warehouse"
    assert "-- Runs inside warehouse (sqlite)" in node["code"]
    with sqlite.connect() as c:
        rows = c.exec_driver_sql(_strip_sql_comments(node["code"])).fetchall()
    assert len(rows) == 20 and {r[0] for r in rows} == {"a"}


def test_live_pandas_node_reads_through_get_engine(sqlite):
    node = nodegen.make_node("sql", FILTERED_CHART, FIELDS[:2], mode="dataset", label="SQL on warehouse",
                             engine="pandas", dialect="sqlite", connection="warehouse",
                             sql="SELECT g, x FROM t WHERE x < 30")["node"]
    assert node["engine"] == "pandas" and "get_engine('warehouse')" in node["code"]
    ns = {"pd": pd, "get_engine": lambda name: sqlite if name == "warehouse" else None}
    exec(node["code"], ns)
    assert len(ns["df"]) == 15 and set(ns["df"]["g"]) == {"a"}


def test_live_node_needs_an_engine():
    with pytest.raises(ValueError, match="Pick an engine"):
        nodegen.make_node("table", FILTERED_CHART, FIELDS, mode="dataset", label="t",
                          dialect="postgres", connection="c", table="t")


def test_python_literal_falls_back_when_unsafe():
    assert nodegen._py_string('SELECT 1') == '"""\nSELECT 1\n"""'
    assert nodegen._py_string('SELECT """x"""') == repr('SELECT """x"""')
    assert nodegen._py_string("SELECT '\\d'") == repr("SELECT '\\d'")


# ── drill-through ─────────────────────────────────────────────────────────────

@pytest.fixture
def drill_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PROJECTS_DIR", str(tmp_path / "projects"))
    return tmp_path / "projects"


CONFIG = {"connection": "warehouse", "table": "t", "keys": [{"field": "g", "column": "g"}]}


def test_config_roundtrip_and_validation(drill_store):
    assert drill.get_config("frame:p:n") is None
    assert drill.set_config("frame:p:n", {**CONFIG, "keys": CONFIG["keys"] + [{"field": "", "column": "x"}]}) == CONFIG
    assert drill.get_config("frame:p:n") == CONFIG
    with pytest.raises(drill.DrillError, match="at least one field"):
        drill.set_config("frame:p:n", {**CONFIG, "keys": []})
    with pytest.raises(drill.DrillError, match="connection and a detail table"):
        drill.set_config("frame:p:n", {"keys": CONFIG["keys"]})
    drill.set_config("frame:p:n", None)
    assert drill.get_config("frame:p:n") is None


def test_settings_file_is_not_listed_as_a_project(drill_store):
    drill.set_config("frame:p:n", CONFIG)
    assert project_service.list_projects() == []


def test_conditions_from_point_and_filters():
    p = {"workflow": [{"type": "filter", "filters": [
        {"fid": "x", "rule": {"type": "range", "value": [1, 9]}},
        {"fid": "ts", "rule": {"type": "temporal range", "value": [0, 1000]}},
        {"fid": "g", "rule": {"type": "not in", "value": ["z"]}},
        {"fid": "gw_bin1", "rule": {"type": "range", "value": [0, 5]}}]}]}
    got = drill.conditions(p, {"g": "a", "x_sum": 10, "gw_q1": 1704067200000}, FIELDS)
    assert got == [("g", "eq", "a"), ("x", "between", [1, 9]), ("ts", "time_between", [0, 1000]),
                   ("g", "not_in", ["z"])]


def test_detail_sql_maps_keys_and_reports_unmapped():
    sql, applied, unmapped = drill.detail_sql(
        [("g", "eq", "a"), ("x", "between", [1, 9]), ("ts", "time_between", [0, 1000])],
        {**CONFIG, "keys": [{"field": "g", "column": "grp"}, {"field": "ts", "column": "event_time"}]},
        FIELDS, "postgres")
    assert sql == ('SELECT * FROM t WHERE "grp" = \'a\' AND "event_time" BETWEEN '
                   "CAST('1970-01-01 00:00:00.000' AS TIMESTAMP(3)) AND CAST('1970-01-01 00:00:01.000' AS TIMESTAMP(3))")
    assert applied == ["g → grp", "ts → event_time"] and unmapped == ["x"]


def test_null_point_value_becomes_is_null():
    sql, _, _ = drill.detail_sql([("g", "eq", None)], CONFIG, FIELDS, "postgres")
    assert sql.endswith('WHERE "g" IS NULL')


def test_run_drill_on_a_live_table(sqlite):
    out = drill.run_drill(sqlite, "sqlite", CONFIG, {"workflow": []}, {"g": "a", "x_sum": 400}, FIELDS)
    assert len(out["rows"]) == 20 and {r["g"] for r in out["rows"]} == {"a"}
    assert out["sql"] == 'SELECT * FROM t WHERE "g" = \'a\'' and out["truncated"] is False


def test_run_drill_refuses_when_nothing_maps(sqlite):
    with pytest.raises(drill.DrillError, match=r"unmapped: x"):
        drill.run_drill(sqlite, "sqlite", CONFIG, {"workflow": []}, {"x": 3}, FIELDS)


# ── endpoints ─────────────────────────────────────────────────────────────────

PID, NID = "proj-1", "node-1"


@pytest.fixture
def client(tmp_path, monkeypatch, sqlite):
    for k, v in {"FRAME_CACHE_DIR": "cache", "PROJECTS_DIR": "projects", "PERSIST_DB": "p/persist.duckdb"}.items():
        monkeypatch.setattr(settings, k, str(tmp_path / v))
    frame_cache.store_frame_arrow(PID, NID, pa.table({"g": [r[0] for r in ROWS], "x": [r[1] for r in ROWS]}))
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / f"{PID}.json").write_text(json.dumps({"id": PID, "name": "Demo", "flows": [
        {"id": "f1", "name": "Flow 1", "nodes": [{"id": NID, "type": "processor", "data": {"label": "Load sales"}}]}]}))
    app = FastAPI()
    app.include_router(explore_api.router, prefix="/api/explore")

    async def no_db():
        yield None
    app.dependency_overrides[get_db] = no_db

    async def engine(_db, name):
        return sqlite, "sqlite"
    monkeypatch.setattr(explore_api, "_engine", engine)
    return TestClient(app)


FRAME = {"kind": "frame", "project_id": PID, "node_id": NID}
AGG = {"workflow": [{"type": "view", "query": [{"op": "aggregate", "groupBy": ["g"], "measures": [
    {"field": "x", "agg": "sum", "asFieldKey": "x_sum"}]}]}]}


def test_node_endpoint_for_a_frame(client):
    d = client.post("/api/explore/node", json={"source": FRAME, "payload": AGG, "mode": "dataset"}).json()
    assert d["node"]["engine"] == "duckdb" and d["node"]["label"] == "Explore · Load sales"
    assert "connect “Load sales” to this node" in d["node"]["code"]


def test_node_endpoint_live_table_both_engines(client):
    src = {"kind": "table", "connection": "warehouse", "table": "t"}
    for engine in ("sql", "pandas"):
        d = client.post("/api/explore/node", json={"source": src, "payload": AGG, "mode": "chart",
                                                    "engine": engine}).json()
        assert d["node"]["engine"] == engine
    r = client.post("/api/explore/node", json={"source": src, "payload": AGG, "mode": "chart"})
    assert r.status_code == 400 and "Pick an engine" in r.json()["detail"]


def test_drill_endpoints(client):
    assert client.get("/api/explore/drill-config", params=FRAME).json() == {"config": None}
    r = client.post("/api/explore/drill", json={"source": FRAME, "payload": AGG, "row": {"g": "a"}})
    assert r.status_code == 400 and "No detail source" in r.json()["detail"]
    assert client.put("/api/explore/drill-config", json={"source": FRAME, "config": CONFIG}).json() == {"config": CONFIG}
    d = client.post("/api/explore/drill", json={"source": FRAME, "payload": AGG, "row": {"g": "b", "x_sum": 1}}).json()
    assert len(d["rows"]) == 20 and d["applied"] == ["g → g"] and d["connection"] == "warehouse"
    live_src = {"kind": "table", "connection": "warehouse", "table": "t"}
    assert client.put("/api/explore/drill-config", json={"source": live_src, "config": CONFIG}).status_code == 400
