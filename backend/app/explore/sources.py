"""Explore sources: where a compiled Graphic Walker query runs.

    frame  — a cached node frame (Arrow IPC), queried by DuckDB without loading it
    table  — a table on an SFS connection, queried live in that database

Each source exposes its data as the relation `compiler.RELATION`, so the same
compiled SQL works for both: a DuckDB view over the frame, or a CTE over the
table for live connections.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.explore import compiler

log = logging.getLogger("sfs.explore")

ROW_CAP = 50_000

_NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
            "UINTEGER", "UBIGINT", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC", "INT")
_TEMPORAL = ("DATE", "TIME", "TIMESTAMP", "DATETIME", "INTERVAL")


@dataclass
class Result:
    rows: list[dict]
    sql: str
    compile_ms: float
    exec_ms: float
    truncated: bool


def gw_field(name: str, sql_type: str) -> dict:
    """Map a column to a Graphic Walker field definition (sqlType kept for the compiler)."""
    t = sql_type.upper()
    base = {"fid": name, "name": name, "sqlType": sql_type}
    if t.startswith(_TEMPORAL) or t.startswith("NULLABLE(DATE"):
        return {**base, "semanticType": "temporal", "analyticType": "dimension"}
    if any(t.startswith(n) for n in _NUMERIC) or "INT" in t or "FLOAT" in t:
        return {**base, "semanticType": "quantitative", "analyticType": "measure"}
    return {**base, "semanticType": "nominal", "analyticType": "dimension"}


def _capped(sql: str, cap: int) -> str:
    return f"SELECT * FROM ({sql}) AS sfs_capped LIMIT {cap + 1}"


# ── frame ─────────────────────────────────────────────────────────────────────

def _frame_con(project_id: str, node_id: str):
    import duckdb
    from app.core.frame_cache import frame_path
    from app.engine.executor import _duckdb_scan

    con = duckdb.connect()
    con.register(compiler.RELATION, _duckdb_scan(frame_path(project_id, node_id)))
    return con


def frame_schema(project_id: str, node_id: str) -> list[dict]:
    # Column names come from DuckDB, not the Arrow schema: DuckDB is
    # case-insensitive and renames case-only duplicates (device → device_1).
    con = _frame_con(project_id, node_id)
    try:
        return [gw_field(r[0], r[1]) for r in con.execute(f'DESCRIBE "{compiler.RELATION}"').fetchall()]
    finally:
        con.close()


def frame_query(project_id: str, node_id: str, payload: dict, cap: int = ROW_CAP) -> Result:
    t0 = time.perf_counter()
    sql = compiler.compile(payload, frame_schema(project_id, node_id))
    t1 = time.perf_counter()
    con = _frame_con(project_id, node_id)
    try:
        cur = con.execute(_capped(sql, cap))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
    t2 = time.perf_counter()
    log.info("explore frame %s/%s %.0f ms: %s", project_id, node_id, (t2 - t1) * 1000, sql)
    return Result(rows[:cap], sql, (t1 - t0) * 1000, (t2 - t1) * 1000, len(rows) > cap)


# ── table (live) ──────────────────────────────────────────────────────────────

def _live_sql(compiled: str, table: str, dialect: str) -> str:
    """Attach the source table as a CTE named RELATION, then transpile."""
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(compiled, read="duckdb")
    src = exp.select("*").from_(exp.to_table(table, dialect=dialect))
    tree = tree.with_(compiler.RELATION, as_=src)
    if dialect == "clickhouse":
        # ClickHouse median() is a sampled estimate; DuckDB median is exact and
        # interpolates between the two middle values, as quantileExactInclusive does.
        tree = tree.transform(lambda n: exp.ParameterizedAgg(
            this="quantileExactInclusive", expressions=[exp.Literal.number(0.5)], params=[n.this],
        ) if isinstance(n, exp.Median) else n)
    return tree.sql(dialect=dialect)


def table_schema(engine, table: str) -> list[dict]:
    import sqlalchemy as sa
    schema, _, name = table.rpartition(".")
    cols = sa.inspect(engine).get_columns(name, schema=schema or None)
    return [gw_field(c["name"], str(c["type"])) for c in cols]


def table_query(engine, dialect: str, table: str, payload: dict, cap: int = ROW_CAP) -> Result:
    t0 = time.perf_counter()
    sql = _live_sql(compiler.compile(payload, table_schema(engine, table)), table, dialect)
    t1 = time.perf_counter()
    with engine.connect() as c:
        # exec_driver_sql: no bind-parameter parsing, so `::` casts survive
        cur = c.exec_driver_sql(_capped(sql, cap))
        cols = list(cur.keys())
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    t2 = time.perf_counter()
    log.info("explore live %s %.0f ms: %s", table, (t2 - t1) * 1000, sql)
    return Result(rows[:cap], sql, (t1 - t0) * 1000, (t2 - t1) * 1000, len(rows) > cap)
