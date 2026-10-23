"""Explore sources: where a compiled Graphic Walker query runs.

    frame    — a cached node frame (Arrow IPC), queried by DuckDB without loading it
    persist  — a table in persist.duckdb, attached read-only for one query
    table    — a table on an SFS connection, queried live in that database

Each source exposes its data as the relation `compiler.RELATION`, so the same
compiled SQL works for all of them: a DuckDB view over the frame or persisted
table, or a CTE over the table for live connections.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.explore import compiler

log = logging.getLogger("sfs.explore")

_NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
            "UINTEGER", "UBIGINT", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC", "INT")
_TEMPORAL = ("DATE", "TIME", "TIMESTAMP", "DATETIME", "INTERVAL")


class QueryTimeout(RuntimeError):
    pass


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


# ── cached: frame | persist (DuckDB) ──────────────────────────────────────────

def _cached_con(kind: str, project_id: str | None = None, node_id: str | None = None,
                table: str | None = None):
    """In-memory DuckDB connection with the source registered as RELATION.

    persist.duckdb is also written by flow runs, and a DuckDB file allows one
    read-write process, so it is attached read-only and only for the lifetime
    of this connection — callers must close it promptly.
    """
    import duckdb

    con = duckdb.connect()
    try:
        if kind == "frame":
            from app.core.frame_cache import frame_path
            from app.engine.executor import _duckdb_scan
            con.register(compiler.RELATION, _duckdb_scan(frame_path(project_id, node_id)))
        elif kind == "persist":
            from app.core.report_store import sanitize_table
            path = Path(settings.PERSIST_DB)
            if not path.exists():
                raise FileNotFoundError("Nothing has been persisted yet")
            con.execute("ATTACH ? AS sfs_persist (READ_ONLY)", [str(path)])
            tbl = sanitize_table(table or "")
            if not con.execute("SELECT 1 FROM duckdb_tables() WHERE database_name = 'sfs_persist'"
                               " AND table_name = ?", [tbl]).fetchone():
                raise FileNotFoundError(f"No persisted table '{tbl}'")
            con.execute(f'CREATE VIEW "{compiler.RELATION}" AS SELECT * FROM sfs_persist."{tbl}"')
        else:
            raise ValueError(f"Unknown cached source kind '{kind}'")
    except BaseException:
        con.close()
        raise
    return con


def _fields(con) -> list[dict]:
    # Column names come from DuckDB, not the Arrow schema: DuckDB is
    # case-insensitive and renames case-only duplicates (device → device_1).
    return [gw_field(r[0], r[1]) for r in con.execute(f'DESCRIBE "{compiler.RELATION}"').fetchall()]


def cached_schema(kind: str, **src) -> dict:
    con = _cached_con(kind, **src)
    try:
        rows = con.execute(f'SELECT count(*) FROM "{compiler.RELATION}"').fetchone()[0]
        return {"fields": _fields(con), "rows": rows}
    finally:
        con.close()


def _run_interruptible(con, sql: str, timeout: float):
    """Execute on DuckDB, interrupting the query if it runs past `timeout` s."""
    import duckdb

    timer = threading.Timer(timeout, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except duckdb.InterruptException:
        raise QueryTimeout(f"Query stopped after {timeout:g} s — filter or aggregate further")
    finally:
        timer.cancel()


def cached_query(kind: str, payload: dict, cap: int | None = None,
                 timeout: float | None = None, **src) -> Result:
    cap = cap or settings.EXPLORE_ROW_CAP
    timeout = timeout or settings.EXPLORE_TIMEOUT_S
    con = _cached_con(kind, **src)
    try:
        t0 = time.perf_counter()
        sql = compiler.compile(payload, _fields(con))
        t1 = time.perf_counter()
        rows = _run_interruptible(con, _capped(sql, cap), timeout)
        t2 = time.perf_counter()
    finally:
        con.close()
    log.info("explore %s %s %.0f ms: %s", kind, src, (t2 - t1) * 1000, sql)
    return Result(rows[:cap], sql, (t1 - t0) * 1000, (t2 - t1) * 1000, len(rows) > cap)


# ── listing ───────────────────────────────────────────────────────────────────

_meta_cache: dict[str, tuple[tuple, dict]] = {}


def _frame_meta(path: Path) -> dict:
    """Row count and columns of a cached frame. Memory-mapped, so no data is
    read, but touching every batch header of a large frame still costs tens of
    ms — results are cached until the file changes."""
    st = path.stat()
    key = (st.st_size, st.st_mtime_ns)
    hit = _meta_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    import pyarrow as pa
    with pa.memory_map(str(path), "rb") as src:
        r = pa.ipc.open_file(src)
        rows = sum(r.get_batch(i).num_rows for i in range(r.num_record_batches))
        meta = {"rows": rows, "columns": len(r.schema), "column_names": r.schema.names[:8]}
    _meta_cache[str(path)] = (key, meta)
    return meta


def list_cached() -> dict:
    """Cached node frames (per project/flow, labelled) and persisted tables."""
    from app.services import project_service

    frames, persisted_by = [], {}
    cache = Path(settings.FRAME_CACHE_DIR)
    for p in project_service.list_projects():
        proj = project_service.get_project(p["id"]) or {}
        for flow in proj.get("flows", []):
            for node in flow.get("nodes", []):
                data = node.get("data") or {}
                if (data.get("persist") or {}).get("table_name"):
                    persisted_by[data["persist"]["table_name"]] = f'{p["name"]} › {data.get("label") or node["id"]}'
                f = cache / p["id"] / f'{node["id"]}.arrow'
                if not f.exists():
                    continue
                try:
                    meta = _frame_meta(f)
                except Exception:
                    continue          # partially written or unreadable frame
                if meta["columns"] == 0:
                    continue          # trigger output: nothing to explore
                frames.append({
                    "kind": "frame", "project_id": p["id"], "node_id": node["id"],
                    "project": p["name"], "flow": flow.get("name", ""),
                    "label": data.get("label") or node.get("type", node["id"]),
                    "node_type": node.get("type"), **meta,
                    "size_bytes": f.stat().st_size, "updated_at": f.stat().st_mtime,
                })

    persisted = []
    path = Path(settings.PERSIST_DB)
    if path.exists():
        import duckdb
        try:
            con = duckdb.connect(str(path), read_only=True)
        except Exception as exc:      # a run is writing it right now
            log.warning("explore: persist.duckdb unavailable: %s", exc)
        else:
            try:
                for name, rows, cols in con.execute(
                        "SELECT table_name, estimated_size, column_count FROM duckdb_tables()"
                        " ORDER BY table_name").fetchall():
                    persisted.append({"kind": "persist", "table": name, "rows": rows, "columns": cols,
                                      "label": name, "node": persisted_by.get(name)})
            finally:
                con.close()
    return {"frames": frames, "persisted": persisted}


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


def table_query(engine, dialect: str, table: str, payload: dict, cap: int | None = None) -> Result:
    cap = cap or settings.EXPLORE_ROW_CAP
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
