# Sidewinder Flow Studio (SFS)

**A visual ETL tool where every node is a Python or SQL cell.** Build data
pipelines on a canvas, inspect the data at any point, and run the heavy work in
pandas, Polars, DuckDB — or push it down into your warehouse.

Think NiFi's canvas, Jupyter's cells, and a DAG — in one self-hosted tool.

> ⚠️ **Early release.** SFS is built and maintained by one person and is under
> active development. It works and is used for real pipelines, but expect rough
> edges. Issues and feedback are very welcome.

<!-- TODO: add a GIF here — drag nodes → run → inspect data → open dashboard -->

---

## Why SFS

Most pipeline tools make you choose: a visual tool that traps you in config
boxes, or code that gives you no visibility into what's happening between steps.

SFS gives you both. Each node holds real code. Between nodes, data is cached as
**Apache Arrow**, so you can click any node and see exactly what came out of it,
re-run from any point without recomputing everything upstream, and mix engines
freely in the same flow.

- **See your data mid-flow** — click any node to inspect its output
- **Re-run surgically** — "run from here" uses cached upstream frames
- **Mix engines per node** — pandas for the fiddly bits, DuckDB/Polars for the heavy lifting
- **Push down when it matters** — run SQL in the warehouse instead of moving rows
- **Bulk-load fast** — `fast_write` uses each database's native loader (1.2M rows to Postgres in ~10s)
- **Self-hosted** — your data never leaves your infrastructure

---

## Features

**Engines** (per node) — pandas · Polars (lazy/streaming) · DuckDB (SQL over Arrow) ·
SQL pushdown (SQLGlot dialect transpilation) · Ibis pushdown

**Connectors** (all free) — PostgreSQL, MySQL, SQLite, SQL Server, Oracle, Druid,
Snowflake, BigQuery, Redshift, ClickHouse, StarRocks, Doris, Trino, Databricks,
Azure Data Lake, Delta Lake, Apache Iceberg

**Nodes** — Trigger (manual/cron) · Processor · Stop/Tap · Table View · Chart ·
Profile (column stats) · Explore (PyGWalker) · Report (Streamlit) · Annotations ·
AI flow-design notes

**Workflow** — multi-input joins/unions · persist & resume checkpoints ·
shared functions · custom reusable processors · run history · scheduling

**AI-assisted** — generate node code from a description (using *your* API key or
a local Ollama model), or sketch a whole flow with AI notes and compile it

**Extensible** — add engines via a documented [plugin contract](docs/PLUGINS.md);
`/api/capabilities` surfaces them in the UI automatically

---

## Quick start

**Docker (recommended):**

```bash
git clone https://github.com/YOUR_USERNAME/sidewinder-flow-studio.git
cd sidewinder-flow-studio
cp .env.docker .env
# generate a key and put it in .env as SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker compose up --build -d
# UI → http://localhost:8080
```

**Local (development):**

```bash
# terminal 1 — backend
cd backend && pip install -e ".[all-connectors,enterprise]" && python main.py

# terminal 2 — frontend
cd frontend && npm install && npm run dev
# UI → http://localhost:5173
```

Full instructions, including the optional reports viewer and per-connector
driver extras: **[docs/INSTALLATION.md](docs/INSTALLATION.md)**

---

## Documentation

| Doc | What's in it |
|---|---|
| [INSTALLATION.md](docs/INSTALLATION.md) | Local, single-container, and multi-container setup |
| [CAPABILITIES.md](docs/CAPABILITIES.md) | Every feature with runnable examples |
| [PLUGINS.md](docs/PLUGINS.md) | Plugin contract for adding engines |
| [AGENTS.md](AGENTS.md) | Context file for AI coding agents |
| [EDITIONS.md](EDITIONS.md) | Open-core vs planned enterprise capabilities |

---

## A 60-second example

```
[Trigger] → [Processor: pandas]  load CSVs from a folder
          → [Processor: DuckDB]  SELECT ... GROUP BY 1  (SQL over the frame)
          → [Profile]            null/distinct/min/max per column
          → [Processor: pandas]  fast_write(df, "warehouse", "public.sales")
          → [Report]             Streamlit dashboard
```

```python
# a processor node — pd, get_engine, fast_write etc. are pre-injected
df = read_files("/data/imports", "sales_*.csv", regex=r"\d{4}-\d{2}-\d{2}")
df = df[df["status"] == "complete"]
fast_write(df, "warehouse", "public.sales", mode="replace")
```

---

## Status & roadmap

Working today: everything in Features above.

Planned: isolated plugin runtimes (run PyCaret/scikit-learn/statsmodels in their
own pinned environments without breaking your ETL env), auth/SSO, worker-queue
scaling, a semantic catalog exposed over MCP, and a desktop build.

See [EDITIONS.md](EDITIONS.md) for the full picture.

---

## Contributing

Issues, bug reports and ideas are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Since this is a solo project, please open an issue before starting large work so
we can agree on direction.

## License

[AGPL-3.0](LICENSE). You can use, modify and self-host SFS freely. If you offer
a modified version as a network service, you must publish your changes.
