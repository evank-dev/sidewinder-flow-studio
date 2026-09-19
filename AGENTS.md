# AGENTS.md — Context for AI agents working with Sidewinder Flow Studio (SFS)

SFS is a visual Python notebook-as-DAG ETL tool: a canvas of nodes (FastAPI
backend, React Flow frontend) where data flows between nodes as Apache Arrow.
This file tells AI agents the conventions they MUST follow when generating or
editing node code, flows, or SFS source.

## The data contract (most important)

- Between every pair of nodes, data is cached as an **Arrow IPC file** and
  exposed to node code as a **pandas DataFrame named `df`** (or engine-native
  equivalent — see engines below).
- **Only the variable `df` passes downstream.** Any other DataFrame created in
  a node (`df1`, `tmp`, …) is discarded when the node finishes. To transform
  the output, REASSIGN df: `df = df[df.col == 'A']`.
- **Multi-input nodes**: first parent → `df`, second → `df2`, third → `df3`;
  `dfs` is the ordered list. Order is a stable sort of parent node ids.
- Node code is `exec()`-ed in an isolated scope per node. Nothing except `df`
  survives across nodes. Flow-level **imports** and **shared_functions**
  (the "Flow Preamble") are exec-ed into EVERY node's scope first.

## Injected names (no import needed, every processor)

| Name | Meaning |
|---|---|
| `pd`, `sa` | pandas, sqlalchemy |
| `get_engine(name)` | SQLAlchemy engine for a named Connection |
| `get_storage(name)` | ADLS storage_options dict for abfs:// paths |
| `read_files(folder, pattern, regex=…)` | load many files → one df (adds `_source_file`) |
| `list_files(folder, pattern, regex=…)` | matching paths |
| `read_tables(conn, [tables], schema=…)` | load many tables → one df (adds `_source_table`) |
| `read_delta(path, storage_conn=None)` | Delta table → df (needs `deltalake` extra) |
| `read_iceberg("ns.table", …)` | Iceberg table → df (needs `pyiceberg` extra) |
| `fast_write(df, conn, table, mode)` | native bulk load — Postgres COPY, ClickHouse native, SQL Server fast_executemany, MySQL/StarRocks/Doris batched executemany, Oracle array bind, Iceberg via pyiceberg; falls back to batched to_sql for others. Use INSTEAD of df.to_sql for large writes |
| `vars` | dict of global Variables (non-secret config) |

`httpx` is a core dependency — use it for API calls (requests is NOT installed).

## Engines (per-processor choice; all read/write Arrow at the boundary)

- **pandas** (default): full Python; leave result in `df`.
- **polars**: `df` is a LazyFrame (scan of upstream IPC). Stay lazy; do NOT
  call `.collect()` — SFS collects (streaming). `pl` injected.
- **duckdb**: code is SQL; upstream frame is table `df` (also `df2`, `df3`).
  Query result becomes the output. Note duckdb >= 1.5: `.arrow()` may return a
  RecordBatchReader — SFS normalizes with `.read_all()`.
- **sql** (enterprise, pushdown): SQL runs IN the target connection's warehouse
  (SQLGlot transpiles dialects). SELECT/WITH results are fetched as the frame;
  DDL/DML (CREATE/COPY/LOAD/MERGE) execute without fetching. Upstream frame is
  NOT available in the warehouse.
- **ibis** (enterprise, pushdown): Python; injected `ibis`, `con` (backend for
  target connection), upstream `df` as memtable. Leave an ibis expression in
  `df`; SFS executes it warehouse-side and pulls the result to pandas.

## Node types

trigger (manual/cron; enterprise scheduler fields: retries, retry_backoff_sec,
alert_on_failure, alert_email, weekdays_only, skip_dates) · processor (code +
engine + optional persist config) · stop (mode hard|tap) · table_out ·
chart_out (set `result` to an echarts dict / plotly fig / matplotlib) ·
profile_out (auto per-column stats) · explore_out (PyGWalker) · report_out
(Streamlit code; `st`, `df`, `pd` injected) · annotation (text only; never
executes) · ai_start / ai_step / ai_end (design-time specs compiled to
processors by "Build with AI"; skipped at run time until built).

## Flow JSON shape (projects/*.json)

Flow = { id, name, active, imports, shared_functions, nodes[], edges[] }.
Node = { id, type, position, data{ label, code, engine, … } }.
Edge = { id, source, target }. Only `df` crosses edges (see contract).

## Engines are pluggable (registry)

Engines are NOT a hard-coded if/elif chain. Each is an `EngineSpec` registered
in `app/engine/registry.py` (builtins register in `executor.py`); the executor
dispatches through the registry. Third-party packages add engines via the
`sfs.plugins` entry-point group — see docs/PLUGINS.md. `GET /api/capabilities`
lists registered engines (with tier/source/availability) and loaded plugins;
the frontend renders the engine picker from it. Unknown engine names in saved
flows fall back to pandas with a warning.

## Backend layout (FastAPI, Python 3.13)

backend/app/: api/ (projects, connections [Fernet-encrypted passwords, PUT
update, dialect-aware build_url], execute [records RunHistory], agent
[generate + /build-flow compile], runs, custom_processors, metadata, ws) ·
engine/executor.py (THE core: build_exec_context, exec_*_processor per engine,
profile_dataframe, execute_flow topological walk) · core/ (frame_cache Arrow
IPC per project/node; report_store reports.duckdb + persist.duckdb) ·
scheduler/ (APScheduler; retries/backoff/alerts/calendar) · services/.
Conventions: lazy-import heavy deps (duckdb, polars, sqlglot, ibis, drivers)
inside functions so the app starts without extras installed; optional drivers
are pyproject extras (`pip install ".[clickhouse]"`, `.[all-connectors]`,
`.[enterprise]`).

## Writing data — use `fast_write`, NOT `df.to_sql`

**`df.to_sql()` is slow and must not be used for bulk loads.** By default it
emits one INSERT per row, which is catastrophically slow for large volumes
(minutes-to-hours, and Trino/Iceberg or other analytical targets are far
worse). ALWAYS prefer the injected `fast_write` helper, which routes each
target to its database's native bulk path:

```python
# Correct — native bulk load, dispatched by the connection's dialect
fast_write(df, "postgres_local", "public.forex", mode="replace")   # append | replace
fast_write(df, "play_clickhouse", "bi.forex", mode="append")
```

Native paths by dialect: **postgresql** → COPY; **clickhouse** → native block
insert; **mssql** → pyodbc `fast_executemany`; **mysql / starrocks / doris** →
driver-batched `executemany`; **oracle** → array binding; **iceberg** →
pyiceberg file append (needs `iceberg_catalog=` + `catalog_props=` — a Trino
connection can query Iceberg but cannot bulk-load it). Any other dialect falls
back to a batched `to_sql(method="multi", chunksize=1000)` automatically —
still better than the row-by-row default.

Only use `df.to_sql(...)` directly if you deliberately need a behaviour
`fast_write` doesn't cover (e.g. letting pandas CREATE a brand-new table from a
tiny result), and even then pass `method="multi"`. For anything more than a few
thousand rows, `fast_write` is the rule, not the exception.

For upserts/merges, load into a temp/staging table with `fast_write` then run
the merge SQL via a SQL-engine node or `get_engine(...).begin()` — don't try to
express upserts through pandas.

## Rules for generated node code

1. No markdown fences, no explanations — code only.
2. Never `import pandas/sqlalchemy` (injected); import stdlib freely.
3. Always leave the result in `df` (or `result` for chart nodes).
4. Use ONLY columns that exist upstream; don't invent schema.
5. Connection names must match configured Connections exactly.
6. Docker note: file paths must be visible to the backend container
   (volume-mounted); `host.docker.internal` reaches the host on Linux via
   compose extra_hosts.
7. **Writing to a database/table: use `fast_write(df, conn, table, mode)`, NOT
   `df.to_sql`.** to_sql is row-by-row and slow; fast_write uses each database's
   native bulk loader. See "Writing data" above.
