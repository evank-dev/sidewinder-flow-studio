"""
Sidewinder Flow Studio (SFS) — DAG Executor

Node types:
  trigger    — entry point (manual or scheduled), no data input
  processor  — arbitrary Python cell, receives `df` emits `df`
  stop       — halts flow (hard) or passes through (tap), caches frame
  table_out  — renders DataFrame as table, flow continues
  chart_out  — renders chart, flow continues
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import traceback
from collections import defaultdict, deque
from typing import Any

import pandas as pd
import pyarrow as pa
import sqlalchemy as sa

from app.core.frame_cache import store_frame, load_frame, has_frame, load_frame_arrow, store_frame_arrow, frame_path
from app.engine.registry import (
    EngineSpec, EngineContext, register_engine, get_engine_spec,
)
from app.core.ws_manager import ws_manager


# ── DAG utilities ─────────────────────────────────────────────────────────────

def topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    ids = [n["id"] for n in nodes]
    in_deg = {i: 0 for i in ids}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adj[e["source"]].append(e["target"])
        in_deg[e["target"]] = in_deg.get(e["target"], 0) + 1

    queue = deque(i for i in ids if in_deg[i] == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for nb in adj[nid]:
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                queue.append(nb)

    if len(order) != len(nodes):
        raise ValueError("Flow contains a cycle.")
    return order


def parents_of(node_id: str, edges: list[dict]) -> list[str]:
    return [e["source"] for e in edges if e["target"] == node_id]


def descendants_of(node_id: str, edges: list[dict]) -> set[str]:
    """All nodes reachable downstream from node_id (its sub-tree)."""
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adj[e["source"]].append(e["target"])
    seen: set[str] = set()
    stack = list(adj[node_id])
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(adj[n])
    return seen


# ── Execution context ─────────────────────────────────────────────────────────

def build_exec_context(
    connections: dict[str, str],
    variables: dict[str, str],
    storage: dict[str, dict] | None = None,
    connect_args: dict[str, dict] | None = None,
    dialects: dict[str, str] | None = None,
) -> dict:
    storage = storage or {}
    connect_args = connect_args or {}
    dialects = dialects or {}

    def get_engine(conn_name: str):
        url = connections.get(conn_name)
        if not url:
            raise ValueError(f"Connection '{conn_name}' not found. Available: {list(connections)}")
        if url.startswith("adls://"):
            raise ValueError(
                f"'{conn_name}' is an Azure Data Lake storage connection — it has no SQL engine. "
                f"Use get_storage('{conn_name}') and read via abfs:// paths, e.g. "
                f"pd.read_parquet('abfs://container/path.parquet', storage_options=get_storage('{conn_name}'))"
            )
        ca = connect_args.get(conn_name) or {}
        return sa.create_engine(url, connect_args=ca) if ca else sa.create_engine(url)

    def get_storage(conn_name: str) -> dict:
        opts = storage.get(conn_name)
        if not opts:
            raise ValueError(
                f"Storage connection '{conn_name}' not found. Available: {list(storage)}"
            )
        return opts

    def read_delta(path: str, storage_conn: str | None = None, **kwargs):
        """Read a Delta Lake table directly to a DataFrame (no query engine).
        `path` is a local path or object-store URI (s3://, gs://, abfs://).
        Pass a storage connection name for cloud auth: read_delta(uri, 'Prod ADLS')."""
        from deltalake import DeltaTable
        opts = storage.get(storage_conn) if storage_conn else None
        dt = DeltaTable(path, storage_options=opts)
        return dt.to_pandas(**kwargs)

    def read_iceberg(table: str, catalog_name: str | None = None, **catalog_props):
        """Read an Apache Iceberg table directly to a DataFrame (no query engine).
        `table` is 'namespace.table'. Supply catalog config via catalog_props
        (e.g. uri=..., type='rest'/'glue'/'sql', or a named catalog in ~/.pyiceberg.yaml)."""
        from pyiceberg.catalog import load_catalog
        cat = load_catalog(catalog_name, **catalog_props) if catalog_props else load_catalog(catalog_name)
        return cat.load_table(table).scan().to_arrow().to_pandas()

    def list_files(folder: str, pattern: str = "*", regex: str | None = None) -> list[str]:
        """List files in a folder. `pattern` is a glob (e.g. 'export_*.csv').
        `regex` optionally further-filters basenames (e.g. r'export_\\d{4}-\\d{2}-\\d{2}').
        Returns sorted absolute paths. In Docker, `folder` must be a path the
        container can see (mount it as a volume)."""
        import glob as _glob, os as _os, re as _re
        paths = sorted(_glob.glob(_os.path.join(folder, pattern)))
        if regex:
            rx = _re.compile(regex)
            paths = [p for p in paths if rx.search(_os.path.basename(p))]
        return paths

    def read_files(folder: str, pattern: str = "*", regex: str | None = None,
                   reader=None, add_source_col: str | None = "_source_file", **read_kwargs):
        """Load every matching file into one concatenated DataFrame.
        Auto-detects csv/parquet/json/xlsx by extension unless `reader` is given
        (a callable like pd.read_csv). Adds a column with the source filename by
        default. Example: read_files('/data/imports', 'export_*.csv',
        regex=r'\\d{4}-\\d{2}-\\d{2}')."""
        import os as _os
        paths = list_files(folder, pattern, regex)
        if not paths:
            raise FileNotFoundError(f"No files matched {folder}/{pattern}" + (f" regex={regex}" if regex else ""))

        def _auto(path):
            ext = _os.path.splitext(path)[1].lower()
            if reader is not None:            return reader(path, **read_kwargs)
            if ext in (".parquet", ".pq"):    return pd.read_parquet(path, **read_kwargs)
            if ext in (".json",):             return pd.read_json(path, **read_kwargs)
            if ext in (".xlsx", ".xls"):      return pd.read_excel(path, **read_kwargs)
            return pd.read_csv(path, **read_kwargs)  # default

        frames = []
        for p in paths:
            part = _auto(p)
            if add_source_col:
                part[add_source_col] = _os.path.basename(p)
            frames.append(part)
        return pd.concat(frames, ignore_index=True)

    def read_tables(connection_name: str, table_names: list[str],
                    schema: str | None = None, add_source_col: str | None = "_source_table"):
        """Load and concatenate several tables from one connection into a single
        DataFrame. Example: read_tables('Prod PG', ['daily_a','daily_b'], schema='sales')."""
        eng = get_engine(connection_name)
        frames = []
        for t in table_names:
            qualified = f"{schema}.{t}" if schema else t
            part = pd.read_sql(f"SELECT * FROM {qualified}", eng)
            if add_source_col:
                part[add_source_col] = t
            frames.append(part)
        return pd.concat(frames, ignore_index=True)

    def fast_write(df, connection_name: str, table: str,
                   mode: str = "append", **kwargs) -> int:
        """
        Bulk-load a DataFrame into a target using the database's NATIVE fast path
        where available, falling back to a batched to_sql otherwise.

        Fast paths: postgresql (COPY), clickhouse (native insert),
        iceberg via a Trino/iceberg connection (pyiceberg file append).
        mode: 'append' | 'replace'  (replace truncates/overwrites first).

        Returns the number of rows written. Far faster than df.to_sql() for
        large volumes because it avoids row-by-row INSERT statements.
        """
        dialect = dialects.get(connection_name, "")
        n = len(df)

        # ── PostgreSQL: COPY via psycopg3 ──────────────────────────────────
        if dialect == "postgresql":
            import io, csv as _csv
            eng = get_engine(connection_name)
            cols = list(df.columns)
            collist = ", ".join(f'"{c}"' for c in cols)
            raw = eng.raw_connection()
            try:
                cur = raw.cursor()
                if mode == "replace":
                    cur.execute(f'TRUNCATE TABLE {table}')
                buf = io.StringIO()
                # Represent NULLs as an unambiguous sentinel so COPY treats them
                # as NULL rather than empty strings.
                w = _csv.writer(buf)
                df_clean = df.where(pd.notnull(df), None)
                for row in df_clean.itertuples(index=False, name=None):
                    w.writerow(["\\N" if v is None else v for v in row])
                buf.seek(0)
                with cur.copy(
                    f"COPY {table} ({collist}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
                ) as cp:
                    cp.write(buf.read())
                raw.commit()
            finally:
                raw.close()
            return n

        # ── ClickHouse: native block insert via clickhouse driver ──────────
        if dialect == "clickhouse":
            eng = get_engine(connection_name)
            if mode == "replace":
                with eng.begin() as c:
                    c.exec_driver_sql(f"TRUNCATE TABLE {table}")
            # SQLAlchemy executemany with clickhouse-sqlalchemy sends a single
            # native multi-row INSERT (block), which is the fast path here.
            cols = list(df.columns)
            collist = ", ".join(cols)
            placeholders = ", ".join([f"%({c})s" for c in cols])
            records = df.to_dict("records")
            with eng.begin() as c:
                c.exec_driver_sql(
                    f"INSERT INTO {table} ({collist}) VALUES",
                    records,
                )
            return n

        # ── Iceberg via pyiceberg (direct catalog write) ───────────────────
        # NOTE: this writes straight to the Iceberg catalog (REST/Hive/Glue),
        # NOT through a Trino connection. A Trino connection queries Iceberg but
        # cannot bulk-load it — pass iceberg_catalog=... + catalog_props=... so
        # pyiceberg can reach the catalog directly.
        if dialect == "iceberg" or kwargs.get("iceberg_catalog"):
            if not kwargs.get("iceberg_catalog") and not kwargs.get("catalog_props"):
                raise ValueError(
                    "fast_write to Iceberg needs a pyiceberg catalog. Pass "
                    "iceberg_catalog='name' and/or catalog_props={'uri': ..., 'type': 'rest'/'glue'/'hive', ...}. "
                    "A Trino connection can't bulk-load Iceberg — it only queries it."
                )
            import pyarrow as _pa
            from pyiceberg.catalog import load_catalog
            cat_name = kwargs.get("iceberg_catalog")
            cat_props = kwargs.get("catalog_props", {})
            cat = load_catalog(cat_name, **cat_props) if cat_props else load_catalog(cat_name)
            tbl = cat.load_table(table)
            arrow_tbl = _pa.Table.from_pandas(df, preserve_index=False)
            if mode == "replace":
                tbl.overwrite(arrow_tbl)
            else:
                tbl.append(arrow_tbl)
            return n

        # ── SQL Server: pyodbc fast_executemany (single flag → bulk) ───────
        if dialect == "mssql":
            eng = get_engine(connection_name)
            if mode == "replace":
                with eng.begin() as c:
                    c.exec_driver_sql(f"TRUNCATE TABLE {table}")
            cols = list(df.columns)
            collist = ", ".join(f"[{c}]" for c in cols)
            qs = ", ".join(["?"] * len(cols))
            rows = [tuple(None if pd.isna(v) else v for v in r)
                    for r in df.itertuples(index=False, name=None)]
            raw = eng.raw_connection()
            try:
                cur = raw.cursor()
                cur.fast_executemany = True          # the speed switch
                cur.executemany(f"INSERT INTO {table} ({collist}) VALUES ({qs})", rows)
                raw.commit()
            finally:
                raw.close()
            return n

        # ── MySQL / MariaDB / StarRocks / Doris: driver-batched executemany ─
        if dialect in ("mysql", "starrocks", "doris"):
            eng = get_engine(connection_name)
            if mode == "replace":
                with eng.begin() as c:
                    c.exec_driver_sql(f"TRUNCATE TABLE {table}")
            cols = list(df.columns)
            collist = ", ".join(f"`{c}`" for c in cols)
            qs = ", ".join(["%s"] * len(cols))
            rows = [tuple(None if pd.isna(v) else v for v in r)
                    for r in df.itertuples(index=False, name=None)]
            raw = eng.raw_connection()
            try:
                cur = raw.cursor()
                # pymysql collapses executemany INSERTs into one multi-row insert
                cur.executemany(f"INSERT INTO {table} ({collist}) VALUES ({qs})", rows)
                raw.commit()
            finally:
                raw.close()
            return n

        # ── Oracle: python-oracledb array binding (native bulk insert) ─────
        if dialect == "oracle":
            eng = get_engine(connection_name)
            if mode == "replace":
                with eng.begin() as c:
                    c.exec_driver_sql(f"TRUNCATE TABLE {table}")
            cols = list(df.columns)
            collist = ", ".join(f'"{c.upper()}"' for c in cols)
            binds = ", ".join(f":{i+1}" for i in range(len(cols)))
            rows = [tuple(None if pd.isna(v) else v for v in r)
                    for r in df.itertuples(index=False, name=None)]
            raw = eng.raw_connection()
            try:
                cur = raw.cursor()
                cur.executemany(f"INSERT INTO {table} ({collist}) VALUES ({binds})", rows)
                raw.commit()
            finally:
                raw.close()
            return n

        # ── Fallback: batched multi-row to_sql (works for any dialect) ─────
        eng = get_engine(connection_name)
        if_exists = "replace" if mode == "replace" else "append"
        df.to_sql(table, eng, if_exists=if_exists, index=False,
                  method="multi", chunksize=kwargs.get("chunksize", 1000))
        return n

    ctx_out = {
        "__builtins__": __builtins__,
        "pd": pd,
        "sa": sa,
        "get_engine": get_engine,
        "get_storage": get_storage,
        "read_delta": read_delta,
        "read_iceberg": read_iceberg,
        "list_files": list_files,
        "read_files": read_files,
        "read_tables": read_tables,
        "fast_write": fast_write,
        "vars": variables,
    }
    return ctx_out


# ── Table serialisation ───────────────────────────────────────────────────────

def df_to_table_payload(df: pd.DataFrame, max_rows: int = 500) -> dict:
    """
    Safely convert a DataFrame to a JSON-serialisable payload.
    Handles PyArrow-backed dtypes and other exotic column types gracefully.
    """
    # Convert to plain Python/numpy-backed DataFrame first to avoid
    # serialisation failures with PyArrow extension types
    try:
        df_plain = df.head(max_rows).copy()
        # Convert any Arrow-backed columns to their numpy equivalents
        for col in df_plain.columns:
            try:
                dtype_str = str(df_plain[col].dtype)
                if '[pyarrow]' in dtype_str or 'ArrowDtype' in dtype_str:
                    df_plain[col] = df_plain[col].to_numpy(dtype=object, na_value=None)
            except Exception:
                df_plain[col] = df_plain[col].astype(str)

        schema = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
        rows = json.loads(df_plain.to_json(orient="records", date_format="iso", default_handler=str))
        return {"schema": schema, "rows": rows, "total": len(df)}
    except Exception as exc:
        # Absolute fallback — return schema only, no rows
        try:
            schema = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
        except Exception:
            schema = []
        return {"schema": schema, "rows": [], "total": len(df), "serialisation_error": str(exc)}


# ── Chart rendering ───────────────────────────────────────────────────────────

def render_chart(df: pd.DataFrame, code: str, ctx: dict) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    local: dict[str, Any] = {**ctx, "df": df.copy(), "result": None}
    exec(code, local)  # noqa: S102

    result = local.get("result")

    try:
        import plotly.graph_objects as go
        if isinstance(result, go.Figure):
            return {"chart_type": "plotly", "payload": result.to_json()}
    except ImportError:
        pass

    if isinstance(result, dict):
        return {"chart_type": "echarts", "payload": json.dumps(result)}

    fig = plt.gcf()
    if fig.get_axes():
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
        plt.close(fig)
        return {"chart_type": "png", "payload": base64.b64encode(buf.read()).decode()}

    raise ValueError("Chart node: set `result` to a plotly Figure, echarts dict, or use matplotlib.")


# ── Data profiling ────────────────────────────────────────────────────────────

def profile_dataframe(df: pd.DataFrame, top_n: int = 5, hist_bins: int = 10) -> pd.DataFrame:
    """
    Per-column profile: dtype, null/distinct counts, most common values, and
    numeric stats (min/max/mean/median/std) with a compact text histogram for
    continuous columns. Returns a tidy DataFrame (one row per column).
    """
    import numpy as np

    n = len(df)
    rows = []
    for col in df.columns:
        s = df[col]
        non_null = s.dropna()
        nulls = int(s.isna().sum())
        distinct = int(non_null.nunique())

        try:
            vc = non_null.value_counts().head(top_n)
            top_vals = ", ".join(f"{k}={v}" for k, v in vc.items())
        except Exception:
            top_vals = ""

        rec = {
            "column": col,
            "dtype": str(s.dtype),
            "count": int(non_null.shape[0]),
            "nulls": nulls,
            "null_pct": round(100 * nulls / n, 2) if n else 0.0,
            "distinct": distinct,
            "distinct_pct": round(100 * distinct / n, 2) if n else 0.0,
            "top_values": top_vals,
        }

        if pd.api.types.is_numeric_dtype(s) and non_null.shape[0] > 0:
            rec["min"] = round(float(non_null.min()), 4)
            rec["max"] = round(float(non_null.max()), 4)
            rec["mean"] = round(float(non_null.mean()), 4)
            rec["median"] = round(float(non_null.median()), 4)
            rec["std"] = round(float(non_null.std()), 4) if non_null.shape[0] > 1 else 0.0
            try:
                counts, _ = np.histogram(non_null.astype(float), bins=hist_bins)
                blocks = "▁▂▃▄▅▆▇█"
                mx = counts.max() or 1
                rec["histogram"] = "".join(
                    blocks[min(len(blocks) - 1, int((c / mx) * (len(blocks) - 1)))] for c in counts
                )
            except Exception:
                rec["histogram"] = ""
        else:
            rec["min"] = rec["max"] = rec["mean"] = rec["median"] = rec["std"] = None
            rec["histogram"] = ""

        rows.append(rec)

    return pd.DataFrame(rows)


# ── Processor execution ───────────────────────────────────────────────────────

def exec_processor(
    code: str,
    df_in: pd.DataFrame | None,
    ctx: dict,
    imports_code: str,
    df_extra: list[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    local: dict[str, Any] = {**ctx, "df": df_in.copy() if df_in is not None else pd.DataFrame()}
    # Additional upstream inputs (joins/unions): df2, df3, … plus `dfs` list
    extras = df_extra or []
    for i, d in enumerate(extras, start=2):
        local[f"df{i}"] = d.copy()
    local["dfs"] = [local["df"]] + [local[f"df{i}"] for i in range(2, 2 + len(extras))]
    if imports_code.strip():
        exec(imports_code, local)  # noqa: S102
    exec(code, local)              # noqa: S102
    result = local.get("df")
    if not isinstance(result, pd.DataFrame):
        raise ValueError("Processor must leave a DataFrame in variable `df`.")
    return result


def exec_duckdb_processor(sql: str, arrow_in: "pa.Table | None", arrow_extra: list | None = None):
    """
    DuckDB engine: run SQL directly over the upstream Arrow tables — zero-copy,
    no pandas in the path. First upstream is table `df`; additional upstreams
    (for joins/unions) are `df2`, `df3`, …  DuckDB spills to disk automatically
    when a query exceeds RAM.

    Returns a pyarrow Table.
    """
    import duckdb  # lazy — backend still starts if duckdb isn't installed

    con = duckdb.connect()  # in-memory database, per-node execution
    try:
        con.register("df", arrow_in if arrow_in is not None else pa.table({}))
        for i, t in enumerate(arrow_extra or [], start=2):
            con.register(f"df{i}", t)

        result = con.execute(sql)
        out = result.arrow()
        # duckdb >= 1.5 returns a streaming RecordBatchReader from .arrow();
        # older versions return a materialized pyarrow.Table. Normalize to Table.
        if not isinstance(out, pa.Table):
            out = out.read_all()
        return out   # result back as Arrow, straight to cache
    finally:
        con.close()


SQLGLOT_DIALECTS = {
    "postgresql": "postgres", "mysql": "mysql", "sqlite": "sqlite", "mssql": "tsql",
    "oracle": "oracle", "druid": "druid", "snowflake": "snowflake", "bigquery": "bigquery",
    "clickhouse": "clickhouse", "redshift": "redshift",
    "trino": "trino", "starrocks": "starrocks", "doris": "doris",
    "databricks": "databricks",
}


def exec_sql_processor(code: str, target_url: str, target_dialect: str, read_dialect: str | None):
    """
    SQL pushdown engine: statements execute IN the target warehouse.
    SQLGlot transpiles from the dialect you wrote (read_dialect) to the target.
    SELECT/CTE results are fetched into a frame; commands (COPY INTO, CREATE,
    LOAD, MERGE, …) are executed and return an empty frame — pure orchestration.
    """
    import sqlglot
    from sqlglot import exp

    write = SQLGLOT_DIALECTS.get(target_dialect, target_dialect)
    read  = SQLGLOT_DIALECTS.get(read_dialect, read_dialect) if read_dialect else write

    try:
        statements = sqlglot.parse(code, read=read)
    except Exception:
        statements = None  # vendor commands sqlglot can't parse — run raw

    eng = sa.create_engine(target_url)
    df_result = pd.DataFrame()
    try:
        if statements:
            with eng.begin() as conn:
                for stmt in statements:
                    if stmt is None:
                        continue
                    sql_out = stmt.sql(dialect=write) if read != write else stmt.sql(dialect=write)
                    if isinstance(stmt, (exp.Select, exp.Union, exp.With)):
                        df_result = pd.read_sql(sa.text(sql_out), conn)
                    else:
                        conn.execute(sa.text(sql_out))
        else:
            # Unparseable vendor command(s) — execute raw, no transpilation
            with eng.begin() as conn:
                for raw in [c.strip() for c in code.split(";") if c.strip()]:
                    conn.execute(sa.text(raw))
    finally:
        eng.dispose()
    return df_result


def exec_ibis_processor(code: str, target_url: str, df_in: pd.DataFrame | None, ctx: dict, imports_code: str) -> pd.DataFrame:
    """
    Ibis pushdown engine: pandas-like Python that compiles to warehouse SQL.
    Injected: `ibis`, `con` (backend for the target connection), `df` (upstream
    frame as an ibis memtable, if any). Leave the result expression in `df`;
    it executes in the warehouse and returns as pandas.
    """
    import ibis

    # ibis.connect() speaks sqlalchemy-style URLs but not driver suffixes
    url = target_url
    for a, b in [("postgresql+psycopg", "postgres"), ("mysql+pymysql", "mysql"),
                 ("mssql+pyodbc", "mssql"), ("redshift+psycopg2", "postgres"),
                 ("clickhouse+http", "clickhouse"), ("oracle+oracledb", "oracle")]:
        url = url.replace(a + "://", b + "://")
    con = ibis.connect(url)

    local: dict[str, Any] = {**ctx, "ibis": ibis, "con": con}
    if df_in is not None and len(df_in):
        local["df"] = ibis.memtable(df_in)
    if imports_code.strip():
        exec(imports_code, local)  # noqa: S102
    exec(code, local)              # noqa: S102

    result = local.get("df")
    if result is None:
        raise ValueError("Ibis processor must leave an ibis expression (or table) in `df`.")
    if isinstance(result, pd.DataFrame):
        return result
    return result.to_pandas()      # executes in the warehouse


def exec_polars_processor(code: str, paths: list[str], ctx: dict, imports_code: str):
    """
    Polars engine: `df` is a LazyFrame scanned from the upstream Arrow IPC file —
    no data loads until the plan collects. Leave the result in `df` (LazyFrame or
    DataFrame); LazyFrames are collected with the streaming engine when available,
    so larger-than-RAM plans can spill. Returns a pyarrow Table.
    """
    import polars as pl  # lazy — backend still starts if polars isn't installed

    local: dict[str, Any] = {**ctx, "pl": pl}
    local["df"] = pl.scan_ipc(paths[0]) if paths else pl.LazyFrame()
    for i, pth in enumerate(paths[1:], start=2):
        local[f"df{i}"] = pl.scan_ipc(pth)
    local["dfs"] = [local["df"]] + [local[f"df{i}"] for i in range(2, len(paths) + 1)]

    if imports_code.strip():
        exec(imports_code, local)  # noqa: S102
    exec(code, local)              # noqa: S102

    result = local.get("df")
    if isinstance(result, pl.LazyFrame):
        try:
            result = result.collect(engine="streaming")   # polars >= 1.x
        except TypeError:
            result = result.collect()
    if not isinstance(result, pl.DataFrame):
        raise ValueError("Polars processor must leave a pl.DataFrame or pl.LazyFrame in `df`.")
    return result.to_arrow()


# ── Built-in engine registrations ─────────────────────────────────────────────
# Each engine is described declaratively and dispatched through the registry,
# so plugins can add engines without modifying this file.

def _run_pandas(ec: "EngineContext"):
    if not ec.code.strip():
        return ec.df_in if ec.df_in is not None else pd.DataFrame()
    return exec_processor(ec.code, ec.df_in, ec.exec_globals, ec.preamble, ec.df_extra)


def _run_duckdb(ec: "EngineContext"):
    if not ec.code.strip():
        return ec.arrow_in if ec.arrow_in is not None else pa.table({})
    return exec_duckdb_processor(ec.code, ec.arrow_in, ec.arrow_extra)


def _run_polars(ec: "EngineContext"):
    if not ec.code.strip():
        return (pa.ipc.open_file(ec.frame_paths[0]).read_all()
                if ec.frame_paths else pa.table({}))
    return exec_polars_processor(ec.code, ec.frame_paths, ec.exec_globals, ec.preamble)


def _run_sql(ec: "EngineContext"):
    return exec_sql_processor(
        ec.code, ec.target_url, ec.target_dialect or "postgresql",
        ec.node_data.get("sql_read_dialect") or None,
    )


def _run_ibis(ec: "EngineContext"):
    return exec_ibis_processor(ec.code, ec.target_url, ec.df_in,
                               ec.exec_globals, ec.preamble)


def _register_builtin_engines() -> None:
    register_engine(EngineSpec(
        name="pandas", label="pandas", description="Python · full flexibility",
        run=_run_pandas, input_mode="pandas", output_mode="pandas",
        language="python", tier="free",
    ))
    register_engine(EngineSpec(
        name="polars", label="Polars", description="Lazy · streaming · fast",
        run=_run_polars, input_mode="paths", output_mode="arrow",
        language="python", tier="free", requires=("polars",),
    ))
    register_engine(EngineSpec(
        name="duckdb", label="DuckDB", description="SQL · zero-copy Arrow",
        run=_run_duckdb, input_mode="arrow", output_mode="arrow",
        language="sql", tier="free", requires=("duckdb",),
    ))
    register_engine(EngineSpec(
        name="sql", label="SQL ⚡", description="Pushdown · SQLGlot · warehouse",
        run=_run_sql, input_mode="none", output_mode="pandas",
        language="sql", tier="enterprise", requires=("sqlglot",),
        needs_target_connection=True,
    ))
    register_engine(EngineSpec(
        name="ibis", label="Ibis ⚡", description="Pushdown · pandas-like · warehouse",
        run=_run_ibis, input_mode="pandas", output_mode="pandas",
        language="python", tier="enterprise", requires=("ibis",),
        needs_target_connection=True,
    ))


_register_builtin_engines()


# ── Main async executor ───────────────────────────────────────────────────────

async def execute_flow(
    project_id: str,
    flow: dict,
    connection_urls: dict[str, str],
    variables: dict[str, str],
    start_from_node: str | None = None,
    resume_from_node: str | None = None,
    storage_options: dict[str, dict] | None = None,
    connection_dialects: dict[str, str] | None = None,
    connection_cargs: dict[str, dict] | None = None,
) -> list[dict]:
    flow_id    = flow["id"]
    nodes      = flow.get("nodes", [])
    edges      = flow.get("edges", [])
    imports_code = flow.get("imports", "")
    shared_functions = flow.get("shared_functions", "")
    # Shared helpers are prepended to imports so they're defined in every node's scope
    preamble_code = (imports_code + "\n" + shared_functions) if shared_functions else imports_code

    if not nodes:
        return []

    try:
        order = topological_sort(nodes, edges)
    except ValueError as e:
        await ws_manager.broadcast(flow_id, {"type": "flow_error", "detail": str(e)})
        return []

    node_map = {n["id"]: n for n in nodes}
    ctx      = build_exec_context(connection_urls, variables, storage_options, connection_cargs, connection_dialects)
    results: list[dict] = []
    flow_start = time.perf_counter()
    # Per-branch blocking: a hard stop blocks only its own descendants,
    # NOT sibling branches. Using a global flag would wrongly halt the whole flow.
    blocked: set[str] = set()
    any_hard_stop = False

    # When running "from here", scope execution to start_from_node + its descendants.
    # Everything else is skipped (their cached frames are reused as inputs).
    run_scope: set[str] | None = None
    if start_from_node:
        run_scope = {start_from_node} | descendants_of(start_from_node, edges)

    # "Resume from persisted": hydrate the node's frame from its persist table,
    # then run ONLY its descendants — the heavy node itself is skipped entirely.
    if resume_from_node and resume_from_node in node_map:
        from app.core import report_store
        rnode = node_map[resume_from_node]
        pconf = rnode.get("data", {}).get("persist") or {}
        tname = pconf.get("table_name") or report_store.sanitize_table(
            rnode.get("data", {}).get("label", resume_from_node)
        )
        try:
            if pconf.get("target", "local") == "local":
                table = report_store.load_persist(tname)
            else:
                url = connection_urls.get(pconf["target"])
                if not url:
                    raise ValueError(f"Connection '{pconf.get('target')}' not found")
                eng = sa.create_engine(url)
                table = pa.Table.from_pandas(pd.read_sql_table(tname, eng))
            store_frame_arrow(project_id, resume_from_node, table)
            await ws_manager.broadcast(flow_id, {
                "type": "node_complete",
                "node_id": resume_from_node,
                "label": rnode.get("data", {}).get("label", "persisted"),
                "rows_in": table.num_rows, "rows_out": table.num_rows,
                "duration_ms": 0, "from_persist": True,
            })
            run_scope = descendants_of(resume_from_node, edges)
        except Exception as e:
            await ws_manager.broadcast(flow_id, {
                "type": "node_error", "node_id": resume_from_node,
                "label": rnode.get("data", {}).get("label", "persisted"),
                "detail": f"Could not load persisted table '{tname}': {e}",
                "duration_ms": 0,
            })
            await ws_manager.broadcast(flow_id, {"type": "flow_complete", "duration_ms": 0, "stopped": False})
            return []

    for node_id in order:
        # Skip nodes that are downstream of a hard stop (blocked branch)
        if node_id in blocked:
            await ws_manager.broadcast(flow_id, {
                "type": "node_blocked",
                "node_id": node_id,
                "label": node_map[node_id].get("data", {}).get("label", node_id),
            })
            continue

        node      = node_map[node_id]
        node_type = node["type"]
        data      = node.get("data", {})
        label     = data.get("label", node_type)

        # Annotation/text nodes are documentation only — never execute.
        # AI notes (ai_start/ai_step/ai_end) are design-time specs; they only
        # run after "Build with AI" converts them into processors.
        if node_type in ("annotation", "ai_start", "ai_step", "ai_end"):
            continue

        # "Run from here" scoping: only execute the start node and its descendants.
        # Nodes outside the scope are skipped — their cached frames feed the scope.
        if run_scope is not None and node_id not in run_scope:
            continue

        await ws_manager.broadcast(flow_id, {
            "type": "node_start",
            "node_id": node_id,
            "label": label,
            "ts": int(time.time() * 1000),
        })

        t0 = time.perf_counter()

        try:
            parent_ids = parents_of(node_id, edges)
            df_in: pd.DataFrame | None = None

            # Engine per node — 'pandas' (default) or 'duckdb'.
            # DuckDB nodes take the Arrow zero-copy path: never load pandas.
            engine = data.get("engine", "pandas") if node_type == "processor" else "pandas"
            spec = get_engine_spec(engine)
            # An engine whose package isn't installed fails with a clear message
            if node_type == "processor":
                ok, why = spec.available()
                if not ok:
                    raise ValueError(
                        f"Engine '{spec.label}' is unavailable: {why}. "
                        f"Install the required extra, or switch this node to another engine."
                    )

            # Multi-input support: a processor can have several upstream nodes
            # (for joins/unions). First parent → `df`, others → `df2`, `df3`, …
            arrow_in = None
            arrow_extra: list = []
            df_extra: list[pd.DataFrame] = []
            polars_paths: list[str] = []

            for i, pid in enumerate(parent_ids):
                if not has_frame(project_id, pid):
                    raise ValueError(
                        f"No cached data for upstream node. "
                        f"Run the full flow once before using 'Run from here'."
                    )
                mode = spec.input_mode
                if mode == "arrow":
                    t = load_frame_arrow(project_id, pid)
                    if i == 0: arrow_in = t
                    else:      arrow_extra.append(t)
                elif mode == "paths":
                    # Lazy: collect file paths only — the engine defers all IO
                    polars_paths.append(frame_path(project_id, pid))
                elif mode == "none":
                    pass  # pushdown: upstream frames are not shipped to the warehouse
                else:      # "pandas"
                    d = load_frame(project_id, pid)
                    if i == 0: df_in = d
                    else:      df_extra.append(d)

            if spec.input_mode == "arrow":
                rows_in = (arrow_in.num_rows if arrow_in is not None else 0) + sum(t.num_rows for t in arrow_extra)
            elif spec.input_mode == "none":
                rows_in = 0
            elif spec.input_mode == "paths":
                import polars as pl  # lazy dep
                rows_in = sum(
                    pl.scan_ipc(pth).select(pl.len()).collect().item()
                    for pth in polars_paths
                ) if polars_paths else 0
            else:
                rows_in = (len(df_in) if df_in is not None else 0) + sum(len(d) for d in df_extra)

            # ── Trigger ───────────────────────────────────────────────────────
            if node_type == "trigger":
                df_out   = pd.DataFrame()
                rows_out = 0
                store_frame(project_id, node_id, df_out)
                duration_ms = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "node_complete",
                    "node_id": node_id, "label": label,
                    "rows_in": 0, "rows_out": 0, "duration_ms": duration_ms,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": 0, "rows_out": 0, "duration_ms": duration_ms,
                })
                continue

            # ── Processor ─────────────────────────────────────────────────────
            elif node_type == "processor":
                code = data.get("code", "")

                # Pushdown engines need a target connection resolved up front
                target_url = target_dialect = None
                if spec.needs_target_connection:
                    target = data.get("target_connection") or ""
                    target_url = connection_urls.get(target)
                    if not target_url:
                        raise ValueError(
                            f"Engine '{spec.label}' needs a target connection — pick one in "
                            f"the node properties. Available: {list(connection_urls)}"
                        )
                    target_dialect = (connection_dialects or {}).get(target, "postgresql")

                ec = EngineContext(
                    code=code, node_data=data, exec_globals=ctx, preamble=preamble_code,
                    df_in=df_in, df_extra=df_extra,
                    arrow_in=arrow_in, arrow_extra=arrow_extra,
                    frame_paths=polars_paths,
                    target_url=target_url, target_dialect=target_dialect,
                )
                result = spec.run(ec)

                # Store according to the engine's declared output type
                if spec.output_mode == "arrow":
                    out_table = result
                    rows_out = out_table.num_rows
                    store_frame_arrow(project_id, node_id, out_table)
                else:
                    df_out = result
                    rows_out = len(df_out)
                    store_frame(project_id, node_id, df_out)

                # ── Persist checkpoint (right-click → Persist) ────────────────
                pconf = data.get("persist") or {}
                if pconf.get("enabled"):
                    from app.core import report_store
                    tname = pconf.get("table_name") or report_store.sanitize_table(label)
                    ptarget = pconf.get("target", "local")
                    out_arrow = out_table if spec.output_mode == "arrow" else pa.Table.from_pandas(df_out)
                    if ptarget == "local":
                        report_store.persist_frame(tname, out_arrow)
                    else:
                        url = connection_urls.get(ptarget)
                        if not url:
                            raise ValueError(f"Persist connection '{ptarget}' not found")
                        peng = sa.create_engine(url)
                        pdf = out_table.to_pandas() if spec.output_mode == "arrow" else df_out
                        pdf.to_sql(tname, peng, if_exists="replace", index=False)
                    await ws_manager.broadcast(flow_id, {
                        "type": "node_persisted",
                        "node_id": node_id, "label": label,
                        "table": tname, "target": ptarget,
                        "rows": rows_out, "ts": int(time.time() * 1000),
                    })

                duration_ms = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "node_complete",
                    "node_id": node_id, "label": label,
                    "rows_in": rows_in, "rows_out": rows_out, "duration_ms": duration_ms,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })
                continue

            # ── Stop / Tap ────────────────────────────────────────────────────
            elif node_type == "stop":
                mode     = data.get("mode", "hard")
                import logging
                logging.getLogger("flowstudio").info(
                    f"STOP node {node_id[:8]} mode={mode!r} "
                    f"{'→ blocking ' + str(descendants_of(node_id, edges)) if mode == 'hard' else '→ pass-through'}"
                )
                df_out   = df_in if df_in is not None else pd.DataFrame()
                rows_out = len(df_out)

                # Always store the frame so downstream nodes can load it
                # AND so the inspect panel can read it
                store_frame(project_id, node_id, df_out)

                # Build table payload separately — catch serialisation errors
                try:
                    table_payload = df_to_table_payload(df_out, max_rows=200)
                except Exception as exc:
                    table_payload = {"schema": [], "rows": [], "total": rows_out,
                                     "serialisation_error": str(exc)}

                duration_ms = round((time.perf_counter() - t0) * 1000)

                await ws_manager.broadcast(flow_id, {
                    "type": "node_stopped",
                    "node_id": node_id, "label": label,
                    "row_count": rows_out,   # integer count — distinct from table_payload["rows"]
                    "duration_ms": duration_ms,
                    "mode": mode,
                    **table_payload,
                })

                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "stopped" if mode == "hard" else "ok",
                    "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })

                if mode == "hard":
                    # Block only this stop's downstream descendants — sibling
                    # branches continue to run normally.
                    blocked |= descendants_of(node_id, edges)
                    any_hard_stop = True
                # For tap mode: frame is stored, flow continues to next node
                continue

            # ── Profile output ────────────────────────────────────────────────
            elif node_type == "profile_out":
                df_in_prof = df_in if df_in is not None else pd.DataFrame()
                rows_in = len(df_in_prof)
                try:
                    df_out = profile_dataframe(
                        df_in_prof,
                        top_n=int(data.get("top_n", 5)),
                        hist_bins=int(data.get("hist_bins", 10)),
                    )
                except Exception as exc:
                    df_out = pd.DataFrame([{"error": str(exc)}])
                rows_out = len(df_out)
                store_frame(project_id, node_id, df_out)

                try:
                    table_payload = df_to_table_payload(df_out, max_rows=500)
                except Exception as exc:
                    table_payload = {"schema": [], "rows": [], "total": rows_out,
                                     "serialisation_error": str(exc)}

                duration_ms = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "table_ready",
                    "node_id": node_id, "label": label,
                    "duration_ms": duration_ms,
                    **table_payload,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })
                continue

            # ── Table output ──────────────────────────────────────────────────
            elif node_type == "table_out":
                df_out   = df_in if df_in is not None else pd.DataFrame()
                rows_out = len(df_out)
                store_frame(project_id, node_id, df_out)

                try:
                    table_payload = df_to_table_payload(df_out, max_rows=500)
                except Exception as exc:
                    table_payload = {"schema": [], "rows": [], "total": rows_out,
                                     "serialisation_error": str(exc)}

                duration_ms = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "table_ready",
                    "node_id": node_id, "label": label,
                    "duration_ms": duration_ms,
                    **table_payload,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })
                continue

            # ── Chart output ──────────────────────────────────────────────────
            elif node_type == "chart_out":
                df_out   = df_in if df_in is not None else pd.DataFrame()
                rows_out = len(df_out)
                code     = data.get("code", "")
                chart_result = render_chart(df_out, code, ctx)
                duration_ms  = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "chart_ready",
                    "node_id": node_id, "label": label,
                    "duration_ms": duration_ms,
                    **chart_result,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })
                continue

            # ── Explore / Report (publish to Streamlit viewer) ────────────────
            elif node_type in ("explore_out", "report_out"):
                from app.core import report_store
                df_out   = df_in if df_in is not None else pd.DataFrame()
                rows_out = len(df_out)
                store_frame(project_id, node_id, df_out)

                kind = "explore" if node_type == "explore_out" else "dashboard"
                report_name = data.get("report_name") or label
                code = data.get("code", "") if kind == "dashboard" else ""

                tbl = report_store.publish_report(
                    report_name, pa.Table.from_pandas(df_out), kind, code
                )

                from app.core.config import settings as _s
                duration_ms = round((time.perf_counter() - t0) * 1000)
                await ws_manager.broadcast(flow_id, {
                    "type": "report_ready",
                    "node_id": node_id, "label": label,
                    "report": tbl, "kind": kind, "rows": rows_out,
                    "url": f"{_s.REPORTS_URL}/?report={tbl}",
                    "duration_ms": duration_ms,
                })
                results.append({
                    "node_id": node_id, "node_type": node_type,
                    "status": "ok", "rows_in": rows_in, "rows_out": rows_out,
                    "duration_ms": duration_ms,
                })
                continue

            else:
                # Unknown node type — pass frame through
                df_out = df_in if df_in is not None else pd.DataFrame()
                store_frame(project_id, node_id, df_out)
                continue

        except Exception:
            tb = traceback.format_exc()
            duration_ms = round((time.perf_counter() - t0) * 1000)
            await ws_manager.broadcast(flow_id, {
                "type": "node_error",
                "node_id": node_id, "label": label,
                "detail": tb, "duration_ms": duration_ms,
            })
            results.append({
                "node_id": node_id, "node_type": node_type,
                "status": "error", "detail": tb, "duration_ms": duration_ms,
            })
            # On error, block only this node's descendants (no frame to pass them).
            # Sibling branches continue — matches the hard-stop behaviour.
            blocked |= descendants_of(node_id, edges)
            continue

    total_ms = round((time.perf_counter() - flow_start) * 1000)
    await ws_manager.broadcast(flow_id, {
        "type": "flow_complete",
        "duration_ms": total_ms,
        "stopped": any_hard_stop,
    })

    return results


def run_flow_sync(project_id: str, flow_id: str):
    """Entry point for APScheduler (synchronous wrapper)."""
    from app.services.project_service import get_project
    from app.services.connection_service import build_url

    project = get_project(project_id)
    if not project:
        return
    flow = next((f for f in project["flows"] if f["id"] == flow_id), None)
    if not flow or not flow.get("active"):
        return

    import sqlalchemy as sa_sync
    from app.core.config import settings
    engine = sa_sync.create_engine(
        settings.METADATA_DB_URL.replace("sqlite+aiosqlite", "sqlite")
    )
    connection_urls = {}
    with engine.connect() as conn:
        rows = conn.execute(sa_sync.text("SELECT name, dialect, host, port, database, username, password_enc FROM connections")).fetchall()
    for row in rows:
        class _MockConn:
            def __init__(self, r):
                self.name = r[0]; self.dialect = r[1]; self.host = r[2]
                self.port = r[3]; self.database = r[4]; self.username = r[5]
                self.password_enc = r[6]
        from app.services.connection_service import build_url as bu
        mc = _MockConn(row)
        connection_urls[mc.name] = bu(mc)

    asyncio.run(execute_flow(project_id, flow, connection_urls, {}))
