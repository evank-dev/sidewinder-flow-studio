# Sidewinder Flow Studio (SFS) — Capabilities & Examples

A visual Python notebook-as-DAG for building, debugging, and scheduling data pipelines — NiFi's canvas meets Jupyter's cells. Every node is code; data flows between nodes as Apache Arrow; you can inspect any edge mid-flight.

This guide walks through every capability with runnable examples.

---

## Core concepts

**The canvas** is a directed graph of nodes. Data flows left to right along the edges. Each node runs, produces a frame, and passes it downstream.

**The Arrow contract.** Between every pair of nodes, data is stored as an Apache Arrow IPC file in the frame cache. This is what makes mixed-engine pipelines work: a pandas node, a Polars node, and a DuckDB node can sit in a chain and hand data to each other with near-zero conversion cost.

**Materialization & inspection.** Because each node's output is cached, you can click any node to inspect its data, and you can re-run from any point without recomputing everything upstream. This inspectability is the core design choice of SFS.

---

## Node types

| Node | Purpose |
|------|---------|
| **Trigger** | Entry point. Manual (click Run) or Schedule (cron). Holds scheduling config. |
| **Processor** | The workhorse. Runs code in one of five engines. Transforms `df`. |
| **Stop / Tap** | Halts a branch (hard) or passes through while marking a checkpoint (tap). |
| **Table View** | Renders the incoming frame as a table. |
| **Chart View** | Renders a chart (ECharts / Plotly / matplotlib). |
| **Explore** | Publishes the frame to the report viewer as a PyGWalker drag-and-drop explorer. |
| **Report** | Publishes an authored Streamlit dashboard to the report viewer. |

---

## The five engines

Each Processor node picks an engine. The engine only changes *how you write the transform* — the input and output are always Arrow frames, so engines mix freely in one flow.

### 1. pandas (default, free)

Full Python flexibility. The incoming frame is `df`; leave the result in `df`.

**Injected without imports:** `pd` (pandas), `sa` (sqlalchemy), `get_engine(name)`, `get_storage(name)`, `vars`.

```python
# Read from a connection, transform, done
engine = get_engine("Prod Postgres")
df = pd.read_sql("SELECT * FROM pbi.mfs_ods_vasp_daily WHERE reference_date >= '2026-01-01'", engine)
df['month'] = pd.to_datetime(df['reference_date']).dt.to_period('M').astype(str)
df = df.groupby('month', as_index=False)['total_loans_count'].sum()
```

### 2. Polars (free)

Lazy and streaming — the upstream frame is scanned as a `LazyFrame`, nothing loads until the plan collects (with the streaming engine, so larger-than-RAM plans can spill). `pl` is pre-injected. Stay lazy; don't call `.collect()` yourself.

```python
df = (df
      .filter(pl.col("projectid") == "gh_mtn_mfs")
      .with_columns(pl.col("reference_date").str.to_date().alias("d"))
      .group_by(pl.col("d").dt.truncate("1mo"))
      .agg(pl.col("total_loans_count").sum()))
```

### 3. DuckDB (free)

Write SQL directly over the upstream frame, which is available as a table named `df`. Zero-copy over Arrow, spills to disk automatically. The query result becomes the node output.

```sql
SELECT date_trunc('month', reference_date::DATE) AS month,
       SUM(total_loans_count) AS loans
FROM df
GROUP BY 1
ORDER BY 1
```

### 4. SQL pushdown (enterprise)

The SQL executes **in the target warehouse**, not on your machine. Pick a target connection in the node. SFS transpiles dialects with SQLGlot, so you can write in one flavor and target another. `SELECT`/`WITH` results become the node output; DDL/DML commands (`CREATE TABLE AS`, `COPY INTO`, `LOAD DATA`, `MERGE`) execute without fetching — perfect for warehouse-to-warehouse orchestration.

```sql
-- Runs inside Snowflake; only the result crosses into SFS
SELECT projectid, SUM(total_loans_count) AS loans
FROM analytics.mfs_ods_vasp_daily
WHERE reference_date >= DATE '2026-01-01'
GROUP BY projectid
```

### 5. Ibis (enterprise)

Pandas-like Python that compiles to warehouse SQL and executes there. Injected: `ibis`, `con` (the target backend), and `df` (upstream frame as a memtable, if any). Leave the result expression in `df`.

```python
t = con.table("analytics.mfs_ods_vasp_daily")
df = (t.filter(t.reference_date >= "2026-01-01")
        .group_by("projectid")
        .aggregate(loans=t.total_loans_count.sum()))
```

**Which engine when?**

- Small/medium data, arbitrary Python, API calls → **pandas**
- Larger single-machine volumes, speed → **Polars** or **DuckDB**
- Data already in a warehouse; push the work down → **SQL** or **Ibis** (enterprise)

---

## Multi-input: joins and unions

A processor can have several upstream nodes. The first is `df`, the rest are `df2`, `df3`, … and `dfs` is the list of all of them. Run three branches in parallel, then merge.

**pandas — join:**
```python
df = df.merge(df2, on='projectid', how='left')
```

**pandas — union of all inputs:**
```python
df = pd.concat(dfs, ignore_index=True)
```

**DuckDB:**
```sql
SELECT * FROM df JOIN df2 USING (projectid)
-- or
SELECT * FROM df UNION ALL SELECT * FROM df2
```

**Polars:**
```python
df = df.join(df2, on="projectid", how="left")   # or pl.concat(dfs)
```

---

## Branching, Stop & Tap, and surgical re-runs

A processor can fan out to multiple downstream branches, which run independently.

- **Stop (hard)** — halts its branch. Only *descendants* of the stop are blocked; sibling branches run normally. Halted edges show a "⊗ halted" badge.
- **Tap** — passes data through unchanged but marks a checkpoint you can inspect.

**Run from here** (right-click a processor) re-runs only that node and its descendants, using cached upstream frames. Nothing else recomputes.

**Release & run this branch** (right-click a hard Stop) flips it to tap and runs just that branch — the workflow for "I stopped this branch, inspected it, now let it through" without re-running the expensive upstream.

---

## Writing data fast — `fast_write`

To load a DataFrame into a database, use the injected `fast_write` helper rather than pandas' `df.to_sql`, which inserts row-by-row and is very slow for large volumes:

```python
fast_write(df, "postgres_local", "public.forex", mode="replace")   # append | replace
```

It automatically uses each database's native bulk loader — PostgreSQL `COPY`, ClickHouse native insert, SQL Server `fast_executemany`, MySQL/StarRocks/Doris batched insert, Oracle array binding, and Iceberg via pyiceberg — falling back to a batched insert for anything else. This is typically 10–100× faster than `to_sql`. For upserts, `fast_write` into a staging table then run your merge SQL via a SQL node.

## Persist & Resume (checkpointing)

Heavy first query you don't want to repeat tomorrow? Right-click a processor → **Persist output**. After each run its output is written to a local DuckDB file (or any configured database connection — the easy way to do `to_sql` without writing it).

Once persisted, the right-click menu offers:

- **Resume from persisted** — hydrates that node's frame from the saved table and runs only its descendants. The heavy node never executes. Works across restarts and days.
- **Flush persisted data** — drops the table so the next run starts fresh from source.

Configure the target (local DuckDB vs. a DB connection) and table name in the Processor panel's Persist section.

---

## Connections (all free)

Add connections in **Meta → Connections**. Passwords are encrypted at rest with your `SECRET_KEY`. Each has a **Test** button.

Supported dialects and what the fields mean:

| Dialect | Host | Database | Extra options (`k=v&k2=v2`) |
|---|---|---|---|
| PostgreSQL / MySQL / SQLite | host | db | — |
| SQL Server | server | db | `driver=ODBC Driver 18 for SQL Server` |
| Oracle | host | **service name** | — (thin mode, no client install) |
| Druid | broker host | `druid/v2/sql` | — |
| Snowflake | account id (`xy12345.eu-central-1`) | `DB/SCHEMA` | `warehouse=WH&role=ANALYST` |
| BigQuery | GCP project | dataset | `credentials_path=/path/key.json` |
| ClickHouse | host | database | `protocol=https` (for port 8443) |
| Redshift | cluster endpoint | db | — (port 5439) |
| Azure Data Lake | storage account | container | `sas_token=...` or `client_id/client_secret/tenant_id` |

**Using a connection in a processor:**
```python
eng = get_engine("Prod Postgres")
df = pd.read_sql("SELECT * FROM schema.table LIMIT 1000", eng)
```

**Azure Data Lake is storage, not SQL** — use `get_storage()`:
```python
opts = get_storage("Prod ADLS")
df = pd.read_parquet("abfs://container/path/data.parquet", storage_options=opts)
df.to_parquet("abfs://container/out/result.parquet", storage_options=opts)
```

---

## Variables

**Meta → Variables** holds reusable config values, available in any processor as `vars`:

```python
cutoff = vars["reporting_start_date"]
df = pd.read_sql(f"SELECT * FROM t WHERE d >= '{cutoff}'", get_engine("Prod Postgres"))
```

Treat variables as non-secret config, not a secrets store (use encrypted Connections for credentials).

---

## The AI agent

Every Processor, Chart, and Report node has a **Generate with AI** button. Describe what you want in plain language; the agent generates code using your **live upstream schema** (column names, dtypes, and a small sample) for context, so it knows your actual columns. It's engine-aware — a DuckDB node gets SQL, a Polars node gets lazy Polars, an Ibis node gets Ibis, a Report node gets Streamlit.

Flow is review-before-insert: it shows the code, notes whether it had your schema, and you accept or retry. Nothing runs automatically.

### AI providers (Meta → AI)

Configure providers in the UI (keys encrypted at rest). Two-tier setup works nicely:

- **Local** — Ollama pointing at `http://localhost:11434` with e.g. `qwen2.5-coder:7b`. No key, runs offline.
- **Premium** — Anthropic Claude with an API key, or any OpenAI-compatible endpoint.

Toggle the active provider with one click; the AgentBox shows which provider generated each snippet. Also supports a legacy `ANTHROPIC_API_KEY` in `.env` as a fallback.

---

## Reports & Explore

Publish data products viewable by people who never open SFS — the optional Streamlit viewer reads a shared DuckDB file.

**Explore node** — no code. Set a report name, run the flow, open the link on the node. You get a PyGWalker drag-and-drop, Tableau-style explorer over the data.

**Report node** — authored dashboard. Write Streamlit code (or have the AI draft it). Pre-injected: `st`, `df`, `pd`.

```python
c1, c2, c3 = st.columns(3)
c1.metric("Rows", len(df))
c2.metric("Total loans", int(df['total_loans_count'].sum()))
c3.metric("Projects", df['projectid'].nunique())

df['month'] = pd.to_datetime(df['reference_date']).dt.to_period('M').astype(str)
st.bar_chart(df.groupby('month')['total_loans_count'].sum())
st.dataframe(df)
```

See INSTALLATION.md for starting the viewer (a third terminal locally, or `--profile reports` in Docker).

---

## Charts inline

The **Chart View** node renders inside the canvas. Set `result` to an ECharts option dict (most reliable), a Plotly figure, or draw with matplotlib.

```python
# ECharts
df_m = df.groupby('market')['revenue'].sum()
result = {
    "xAxis": {"data": df_m.index.tolist()},
    "yAxis": {},
    "series": [{"type": "bar", "data": df_m.values.tolist()}]
}
```

```python
# Plotly
import plotly.express as px
result = px.line(df, x="month", y="loans", color="projectid")
```

---

## Scheduling

On the **Trigger** node, switch Run Mode to **Schedule** and set a cron expression + timezone.

```
0 6 * * 1-5     # weekdays at 06:00
0 */4 * * *     # every 4 hours
30 2 1 * *      # 02:30 on the 1st of each month
```

**Free:** basic cron scheduling.

**Enterprise scheduler** adds, on the same trigger node:

- **Retries** with **exponential backoff** (`wait × 2^(attempt−1)`)
- **Failure alerting** — Slack webhook + email (configure `SLACK_WEBHOOK_URL` / `SMTP_*` in `.env`)
- **Calendar rules** — weekdays-only, and a skip-dates list for holidays
- **Run history / audit** — every run and retry recorded, visible in **Meta → Runs** (status, trigger, attempt, duration, node counts, errors)

---

## Worked example: warehouse-to-warehouse transfer

Move aggregated data from Snowflake to BigQuery, orchestrated by SFS — the data never touches your machine.

```
[Trigger: schedule 0 5 * * *]
        │
[Processor · SQL engine · target = Snowflake]
   COPY INTO @gcs_stage/loans
   FROM (SELECT projectid, reference_date, total_loans_count
         FROM analytics.mfs_ods_vasp_daily
         WHERE reference_date >= DATEADD(day, -1, CURRENT_DATE))
   FILE_FORMAT = (TYPE = PARQUET);
        │
[Processor · SQL engine · target = BigQuery]
   LOAD DATA INTO analytics.loans_daily
   FROM FILES (format='PARQUET', uris=['gs://my-stage/loans/*']);
        │
[Processor · SQL engine · target = BigQuery]   -- validation
   SELECT COUNT(*) AS rows_loaded FROM analytics.loans_daily;
        │
[Table View]   -- the small validation result is fine to pull into pandas
```

Both bulk steps run inside the warehouses; only the final count crosses into SFS.

---

## Worked example: daily P&L dashboard

```
[Trigger: schedule 0 6 * * 1-5, retries=2, alert_on_failure=on, weekdays_only=on]
        │
[Processor · pandas]   read raw P&L from Postgres, cast dates
        │
[Processor · DuckDB]   SELECT ... aggregate by cost center & month
        │
[Persist: ON → local]  checkpoint the aggregate
        │
        ├─[Report node]   authored Streamlit KPI dashboard
        └─[Explore node]  PyGWalker explorer for ad-hoc slicing
```

Runs every weekday at 06:00, retries twice with backoff on failure, alerts on final failure, and publishes both a curated dashboard and a self-serve explorer.

---

## Tips

- **Inspect liberally.** Click any node after a run to see its data. Tap edges you're unsure about.
- **Persist heavy nodes** early in development so you're not re-running expensive source queries on every iteration.
- **Keep engines per-node.** Use pandas for the fiddly Python bits and SQL/DuckDB/Polars for the heavy relational work; the Arrow boundaries between them are cheap.
- **Let the agent draft, then read it.** Especially for charts and Streamlit reports where the boilerplate is tedious.
- **Push down at scale.** The further you push filtering/aggregation toward the source (SQL/Ibis engines, or SQL in a pandas node), the less data crosses into SFS.
