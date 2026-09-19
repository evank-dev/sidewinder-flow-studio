# Sidewinder Flow Studio (SFS) — Installation Guide

This guide covers three ways to run SFS:

1. **Local (terminals)** — best for development and daily personal use
2. **Single Docker container** — simplest deployment; one image serves everything
3. **Multi-container Docker (2–3 containers)** — production-style; backend, frontend, and optional report viewer as separate services

Pick the one that matches your situation. All three share the same data model, so you can move between them.

---

## Before you start

**Requirements**

| Mode | Needs |
|------|-------|
| Local | Python 3.11+, Node.js 18+, (optional) conda/venv |
| Docker (any) | Docker 24+ and Docker Compose v2 |

**Generate a SECRET_KEY** (used to encrypt stored connection passwords and API keys). You'll need this for every mode:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — it's a ~44-character string ending in `=`. Keep it stable: if you change it later, previously saved connection passwords can no longer be decrypted.

---

## Option 1 — Local (three terminals)

This runs the backend, the frontend dev server, and (optionally) the report viewer as separate processes. It's the recommended setup while building flows because you get hot-reload on both frontend and backend.

### 1. Backend (terminal 1)

```bash
cd backend

# Recommended: isolate dependencies in a conda env or venv
conda create -n sfs python=3.12 -y && conda activate sfs
#   ...or:  python -m venv .venv && source .venv/bin/activate

# Install the core plus any optional connector/enterprise extras you need
pip install -e .                         # core (pandas, polars, duckdb engines)
pip install -e ".[enterprise]"           # + SQL pushdown & Ibis engines
pip install -e ".[snowflake,bigquery]"   # + specific warehouse drivers (see table below)
```

Create `backend/.env`:

```ini
SECRET_KEY=<paste the key you generated>
DEBUG=true

# Where SFS stores its data. IMPORTANT on Windows: keep these OUT of
# OneDrive/Dropbox synced folders — sync locks corrupt the DuckDB files.
PROJECTS_DIR=./projects
FRAME_CACHE_DIR=./frame_cache
REPORTS_DIR=./reports_data
PERSIST_DB=./reports_data/persist.duckdb
REPORTS_URL=http://localhost:8501

# Optional: AI agent (or configure providers in the UI instead)
ANTHROPIC_API_KEY=

# Optional: enterprise scheduler failure alerts
SLACK_WEBHOOK_URL=
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=sfs@localhost
```

Start it:

```bash
python main.py
# → backend on http://localhost:8000  (API docs at /docs)
```

### 2. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
# → UI on http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to `localhost:8000` automatically, so just open **http://localhost:5173**.

### 3. Report viewer (terminal 3, optional)

Only needed if you use **Explore** or **Report** nodes. Best practice is a *separate* environment, because the viewer pins specific Streamlit/PyGWalker versions that you don't want constraining your main env:

```bash
conda create -n sfs-reports python=3.12 -y && conda activate sfs-reports
cd reports-app
pip install -r requirements.txt          # pinned streamlit==1.41.1 + pygwalker==0.5.0.1

# Point it at the SAME reports DB the backend writes to:
export REPORTS_DB=../backend/reports_data/reports.duckdb   # Windows: set REPORTS_DB=...
streamlit run app.py
# → viewer on http://localhost:8501
```

The viewer is fully optional and independent — start it whenever, or never. The only link between it and the backend is the shared `reports.duckdb` file.

### Makefile shortcuts

```bash
make dev-backend     # terminal 1
make dev-frontend    # terminal 2
make gen-key         # print a fresh SECRET_KEY
```

---

## Option 2 — Single Docker container

One image runs the FastAPI backend and serves the pre-built frontend from the same port. Simplest possible deployment; good for a personal server or a quick trial. The report viewer is **not** included in single-container mode — use local or multi-container if you need it.

```bash
# 1. Create .env
cp .env.docker .env
#    edit .env and set SECRET_KEY (use: make gen-key)

# 2. Build and start
docker compose -f docker-compose.single.yml up --build -d

# → everything on http://localhost:8000
```

Data (projects, cache, metadata DB, reports) lives in a named Docker volume `flow_data`, so it survives restarts and rebuilds.

```bash
make docker-single          # same thing via Makefile
make docker-single-down     # stop
```

To include enterprise engines or warehouse drivers in the image, add them to `backend/pyproject.toml`'s dependencies (or the Dockerfile's pip install) before building.

---

## Option 3 — Multi-container Docker (2–3 containers)

Production-style. Separate containers:

- **backend** — FastAPI + engines (internal, not exposed directly)
- **frontend** — nginx serving the built UI, reverse-proxying `/api` and `/ws` to the backend (exposed on `:8080`)
- **reports** — the Streamlit viewer (optional; only starts with a profile flag)

They share a Docker volume so the reports container can read what the backend writes (read-only mount — the backend is the single writer).

### Two containers (backend + frontend)

```bash
# 1. Create and edit .env
cp .env.docker .env
#    set SECRET_KEY; optionally FRONTEND_PORT (default 8080)

# 2. Start
docker compose up --build -d

# → UI on http://localhost:8080
```

```bash
make docker            # same via Makefile
make docker-down       # stop
make docker-logs       # tail logs
```

### Three containers (add the report viewer)

The reports service is behind a Compose **profile**, so it only starts when you ask for it:

```bash
docker compose --profile reports up --build -d

# → UI       on http://localhost:8080
# → Reports  on http://localhost:8501
```

Relevant `.env` knobs:

```ini
SECRET_KEY=<required>
FRONTEND_PORT=8080     # UI port
REPORTS_PORT=8501      # report viewer port
```

### Environment / data notes

- All persistent data lives in the `flow_data` named volume. To use a host directory instead, uncomment the `driver_opts` bind block at the bottom of `docker-compose.yml` and point `device:` at your path.
- The backend container reads env vars directly from the compose file (`PROJECTS_DIR=/data/...`, etc.) — you don't need a separate `backend/.env` in Docker mode.
- To add AI or alerting in Docker, add the vars (`ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `SMTP_*`) to the `backend` service's `environment:` block.

---

## Warehouse driver extras

Connectors are all free, but their Python drivers are optional installs so the base image stays lean. Install only what you use:

```bash
pip install -e ".[snowflake]"      # snowflake-sqlalchemy + connector
pip install -e ".[bigquery]"       # sqlalchemy-bigquery + google-cloud-bigquery
pip install -e ".[clickhouse]"     # clickhouse-sqlalchemy
pip install -e ".[redshift]"       # sqlalchemy-redshift + psycopg2
pip install -e ".[mssql]"          # pyodbc  (also needs the OS-level MS ODBC driver)
pip install -e ".[oracle]"         # oracledb (thin mode; no Oracle client needed)
pip install -e ".[mysql]"          # pymysql
pip install -e ".[druid]"          # pydruid
pip install -e ".[adls]"           # adlfs (Azure Data Lake storage)
pip install -e ".[enterprise]"     # sqlglot + ibis-framework (SQL & Ibis engines)
pip install -e ".[all-connectors]" # everything above
```

PostgreSQL, MySQL, SQLite, and Druid basics work out of the box.

> **SQL Server note:** `pyodbc` needs the Microsoft ODBC Driver 18 installed at the OS level — that part can't come from pip.

---

## Verifying the install

1. Open the UI (`:5173` local, `:8080` multi-container, `:8000` single).
2. Click the **FS** logo (top-left) → the About dialog shows the version.
3. Create a project, drop a **Trigger** and a **Processor**, connect them, put `df = pd.DataFrame({'x':[1,2,3]})` in the processor, and hit **Run Flow**.
4. The processor should show `3 rows`. If so, you're good.

For the reports viewer, add an **Explore** node after a processor, run, then open the link on the node (or browse to `:8501`).

---

## Common issues

| Symptom | Fix |
|---|---|
| Saved connection passwords stop working | `SECRET_KEY` changed — restore the original key |
| Report viewer: "PyGWalker not installed" | Restart the **viewer** terminal (packages installed after start aren't seen); ensure `streamlit==1.41.1` + `pygwalker==0.5.0.1` |
| `IO Error ... file is being used by another process` (Windows) | Move data dirs out of OneDrive/Dropbox; the viewer now uses short-lived connections but synced folders still interfere |
| Engine errors "sqlglot/ibis not installed" | `pip install -e ".[enterprise]"` |
| Warehouse connection fails on Test | Check the driver extra is installed; for Snowflake verify the account-identifier format in the Host field |
| Frontend can't reach backend (local) | Confirm backend is on :8000; the Vite proxy targets that port |
