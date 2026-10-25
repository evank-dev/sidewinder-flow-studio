"""Explore compiler wrapper (Phase 0): golden SQL, dialects, isolation."""
import os

import duckdb
import pyarrow as pa
import pytest

from app.explore import compiler
from app.explore.live import live_sql
from app.explore.sources import gw_field


def _live_sql(compiled, table, dialect):
    from app.explore.live import relation_sql
    return live_sql(compiled, relation_sql("table", dialect, table=table), dialect, 50_000)

AGG = {"workflow": [{"type": "view", "query": [{"op": "aggregate", "groupBy": ["gt"], "measures": [
    {"field": "x", "agg": "mean", "asFieldKey": "x_mean"}]}]}]}
MEDIAN = {"workflow": [{"type": "view", "query": [{"op": "aggregate", "groupBy": ["gt"], "measures": [
    {"field": "z", "agg": "median", "asFieldKey": "z_median"}]}]}]}


def test_golden_duckdb():
    assert compiler.compile(AGG) == (
        'SELECT "gt", avg("x") AS "x_mean" FROM (SELECT * FROM "sfs_src") AS "k6s_base_table" GROUP BY "gt"')


def test_filter_and_limit():
    sql = compiler.compile({"workflow": [
        {"type": "filter", "filters": [{"fid": "Device", "rule": {"type": "one of", "value": ["a", "b"]}}]},
        {"type": "view", "query": [{"op": "raw", "fields": ["x"]}]}], "limit": 10})
    assert "\"Device\" IN ('a', 'b')" in sql and sql.endswith("LIMIT 10")


def test_invalid_payload_raises():
    with pytest.raises(Exception):
        compiler.compile({"workflow": [{"type": "nonsense"}]})


def test_compiled_sql_runs_on_duckdb():
    con = duckdb.connect()
    con.register("sfs_src", pa.table({"gt": ["a", "a", "b"], "x": [1.0, 3.0, 5.0]}))
    rows = dict(con.execute(compiler.compile(AGG)).fetchall())
    assert rows == {"a": 2.0, "b": 5.0}


def test_wasm_gets_no_environment(monkeypatch):
    # The package's own entry point inherits os.environ into WASI; ours must not.
    monkeypatch.setenv("SECRET_KEY", "must-not-leak")
    assert compiler.compile(AGG)  # still works with an empty WASI config


def test_memory_does_not_grow_per_call():
    import resource
    for _ in range(50):
        compiler.compile(AGG)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(500):
        compiler.compile(AGG)
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert grown_mb < 20, f"compiler leaked ~{grown_mb:.0f} MB over 500 calls"


def test_live_sql_wraps_table_as_cte_clickhouse():
    sql = _live_sql(compiler.compile(AGG), "default.hhar", "clickhouse")
    assert sql.startswith('WITH "sfs_src" AS (\nSELECT * FROM default.hhar\n)\n')
    assert sql.endswith("AS sfs_capped LIMIT 50001")


def test_clickhouse_median_is_exact():
    sql = _live_sql(compiler.compile(MEDIAN), "default.hhar", "clickhouse")
    assert 'quantileExactInclusive(0.5)("z")' in sql
    assert "median(" not in sql


def test_postgres_median_transpiles():
    sql = _live_sql(compiler.compile(MEDIAN), "employees.salary", "postgres")
    assert "PERCENTILE_CONT(0.5) WITHIN GROUP" in sql


@pytest.mark.parametrize("t,sem", [("BIGINT", "quantitative"), ("DOUBLE", "quantitative"),
                                   ("TIMESTAMP", "temporal"), ("DATE", "temporal"),
                                   ("VARCHAR", "nominal"), ("Nullable(Float64)", "quantitative")])
def test_gw_field_types(t, sem):
    assert gw_field("c", t)["semanticType"] == sem


TS_FIELDS = [{"fid": "datetime", "semanticType": "temporal", "sqlType": "TIMESTAMP"},
             {"fid": "base", "semanticType": "nominal"}, {"fid": "bid", "semanticType": "quantitative"}]


def _fx_con():
    con = duckdb.connect()
    con.execute("CREATE TABLE sfs_src AS SELECT TIMESTAMP '2024-01-15 10:00' + INTERVAL (i) DAY AS datetime,"
                " 'EUR' AS base, i * 1.0 AS bid FROM range(100) t(i)")
    return con


def test_field_meta_format():
    assert compiler.field_meta(TS_FIELDS) == {"sfs_src": [
        {"key": "datetime", "type": "datetime"}, {"key": "base", "type": "string"},
        {"key": "bid", "type": "number"}]}


def test_temporal_range_filter_needs_and_uses_meta():
    p = {"workflow": [
        {"type": "filter", "filters": [{"fid": "datetime", "rule": {
            "type": "temporal range", "value": [1706745600000, 1709251200000]}}]},   # Feb 2024
        {"type": "view", "query": [{"op": "aggregate", "groupBy": ["base"], "measures": [
            {"field": "bid", "agg": "sum", "asFieldKey": "s"}]}]}]}
    con = _fx_con()
    with pytest.raises(duckdb.BinderException):          # what GW gets without types
        con.execute(compiler.compile(p)).fetchall()
    got = con.execute(compiler.compile(p, TS_FIELDS)).fetchone()[1]
    want = con.execute("SELECT sum(bid) FROM sfs_src WHERE datetime >= '2024-02-01'"
                       " AND datetime < '2024-03-01'").fetchone()[0]
    assert got == want


@pytest.mark.parametrize("op,level", [("dateTimeDrill", "month"), ("dateTimeFeature", "weekday")])
def test_date_ops_run_on_timestamps(op, level):
    p = {"workflow": [
        {"type": "transform", "transform": [{"key": "d", "expression": {"op": op, "as": "d", "params": [
            {"type": "field", "value": "datetime"}, {"type": "value", "value": level}]}}]},
        {"type": "view", "query": [{"op": "aggregate", "groupBy": ["d"], "measures": [
            {"field": "bid", "agg": "mean", "asFieldKey": "b"}]}]}]}
    rows = _fx_con().execute(compiler.compile(p, TS_FIELDS)).fetchall()
    assert len(rows) == (4 if level == "month" else 7)
