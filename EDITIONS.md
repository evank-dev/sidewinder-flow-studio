# SFS Editions — Open Core vs Enterprise

This document maps every SFS capability to its intended **edition** (open-source
vs enterprise) and, for enterprise features, its **current implementation
state** — specifically whether it is already separated into a pluggable module
or still embedded in the core code.

Status legend:
- ✅ **Implemented** — built and working
- 🟡 **Partial** — works but incomplete or not production-hardened
- ⬜ **Planned** — designed/discussed, not yet built

Enterprise separation legend (for implemented enterprise features):
- 🔗 **Embedded** — code lives inside core files, gated by a check; NOT yet
  extractable to a private repo without refactoring
- 🧩 **Pluggable** — already isolated so it could live in a separate package

> **Key architectural note.** No plugin/entry-point loader, license system, or
> auth layer exists yet. Every "enterprise" feature that is implemented today is
> **embedded (🔗)** in the open codebase, gated only by a dialect or field
> check. Cleanly splitting a private enterprise repo requires the
> **engine-registry + plugin-loader refactor** (see "Pre-split work" below).
> Until then, the whole codebase is effectively one open product.

---

## Open-core capabilities (free, AGPL-3.0)

These are the complete, genuinely useful free product. Nothing here is crippled.

### Canvas & flow authoring
- ✅ Visual DAG canvas (React Flow) — drag nodes, wire edges
- ✅ Per-node code cells (Monaco editor)
- ✅ Multi-flow projects
- ✅ Node inspection — click any node to view its cached data
- ✅ Edge labels showing variable name (`df`/`df2`) + row count
- ✅ Input-variable chips in the processor panel
- ✅ Annotation notes (colored, resizable, render behind, never execute)
- ✅ Run-from-here / resume / branch execution controls

### Execution engines (per-processor choice)
- ✅ **pandas** — full Python
- ✅ **Polars** — lazy, streaming, Arrow-native
- ✅ **DuckDB** — SQL over the upstream Arrow frame, zero-copy
- ✅ Arrow IPC contract between all nodes (mixed engines interoperate)

### Data movement
- ✅ Multi-input joins/unions (`df`, `df2`, `df3`, `dfs`)
- ✅ `read_files` / `list_files` — multi-file loading with glob + regex
- ✅ `read_tables` — multi-table loading
- ✅ `read_delta` / `read_iceberg` — direct table-format reads
- ✅ **`fast_write`** — native bulk load (Postgres COPY, ClickHouse native,
  SQL Server fast_executemany, MySQL/StarRocks/Doris batched, Oracle array
  bind, Iceberg via pyiceberg; batched to_sql fallback)
- ✅ Persist & Resume (checkpoint node output to DuckDB or a DB connection)

### Connectors (all free — breadth is not gated)
- ✅ PostgreSQL, MySQL, SQLite, SQL Server, Oracle, Druid (core/opt drivers)
- ✅ Snowflake, BigQuery, Redshift, ClickHouse
- ✅ StarRocks, Doris, Trino, Databricks
- ✅ Azure Data Lake (storage, via `get_storage`)
- ✅ Delta & Iceberg (table formats — via engine or direct helpers)
- ✅ Connection management: create / edit / delete / test, Fernet-encrypted
  credentials, dialect-aware URL building, Trino auth/verify connect_args

### Outputs & inspection
- ✅ Table View node
- ✅ Chart View node (ECharts / Plotly / matplotlib)
- ✅ Profile node (per-column stats: nulls, distinct, top values, numeric
  stats, text histogram)
- ✅ Explore node (PyGWalker, no-code exploration)
- ✅ Report node (Streamlit dashboards)
- ✅ Streamlit reports viewer app

### Extensibility
- ✅ **Engine registry + plugin system** — add engines via `sfs.plugins` entry
  points, no core changes (docs/PLUGINS.md)
- ✅ `/api/capabilities` — engines/plugins/features discovery; UI renders from it

### Productivity
- ✅ Shared functions / imports preamble (flow-level)
- ✅ Custom processors (save a processor, reuse via toolbar drag)
- ✅ Variables (global config dict)
- ✅ Built-in AI agent — code generation per engine/node type (uses user's own
  provider: Anthropic / Ollama / OpenAI-compatible)
- ✅ AI Flow Builder — design with AI Start/Step/End notes, "Build with AI"
  compiles them into processors (topological, schema-threaded)
- ✅ Basic cron scheduling (trigger node, cron + timezone)
- ✅ `AGENTS.md` context file for external AI agents

### Ops & deployment
- ✅ Local run (3 processes) and Docker (single / multi-container)
- ✅ Self-healing data directories, SECRET_KEY encryption
- ✅ Run history / audit table + Runs panel

---

## Enterprise capabilities

### Already implemented (but embedded — see separation column)

| Capability | Status | Separation | Notes |
|---|---|---|---|
| **SQL pushdown engine** (SQLGlot dialect transpilation; runs in-warehouse) | ✅ | 🔗 Embedded | Lives in `executor.py` (`exec_sql_processor`), gated by `engine == "sql"`. Needs extraction. |
| **Ibis pushdown engine** (pandas-like, compiles to warehouse SQL) | ✅ | 🔗 Embedded | `exec_ibis_processor` in `executor.py`, gated by `engine == "ibis"`. |
| **Pro scheduler** — retries + exponential backoff | ✅ | 🔗 Embedded | In `scheduler.py`, read from trigger-node fields. |
| **Pro scheduler** — failure alerting (Slack + email) | ✅ | 🔗 Embedded | `alert_service.py` + scheduler; config in `.env`. |
| **Pro scheduler** — calendar rules (weekdays-only, skip-dates) | ✅ | 🔗 Embedded | In `scheduler.py`. |
| **Pro scheduler** — per-attempt run history/audit | ✅ | 🔗 Embedded | Shared with the free Runs panel (the panel is free; retries/alerts are the paid part). |

> All six above are **gated by a simple check, not a license** — today anyone
> running the open code can use them. Making them paid requires (a) the plugin
> split and (b) the licensing system, both below.

### Planned (not yet built)

| Capability | Status | Intended separation | Notes |
|---|---|---|---|
| **Engine-registry + plugin loader** (entry-points; `/api/capabilities`) | ✅ | Core (open) enabling layer | DONE — `app/engine/registry.py`, contract in docs/PLUGINS.md. Engines are now pluggable; enterprise engines still ship in-tree but are registered like any plugin. |
| **Licensing** — Ed25519 offline-signed keys, seat/expiry/features | ⬜ | 🧩 Plugin | Verifies offline; perpetual = `expires:null`. |
| **Auth — local** (argon2 + JWT), login, WS token validation | ⬜ | 🧩 Plugin | Interface stub in open core, impl in enterprise. |
| **Auth — SSO/OIDC** (Azure AD etc.) | ⬜ | 🧩 Plugin | The #1 enterprise procurement ask. |
| **RBAC** (viewer/editor/admin; viewers see reports only) | ⬜ | 🧩 Plugin | Pairs with reports. |
| **Isolated plugin runtime** — one container, multiple pinned venvs, Arrow/parquet handoff (PyCaret, Prophet, statsmodels…) | ⬜ | 🧩 Separate container | Curated, version-tested heavy libs without breaking the app. |
| **Worker queue scaling** — Celery/RQ workers, Postgres metadata, shared frame store | ⬜ | 🧩 Plugin + infra | Removes the single-process concurrency ceiling. |
| **Vector/MCP semantic catalog** — profile tables + DAG lineage → catalog → expose as MCP server for AI tools | ⬜ | 🧩 Plugin | Flagship AI-native differentiator. |
| **Pushdown-aware profiling** — compute stats in-database, return only the stats | ⬜ | 🧩 Plugin | Pairs with catalog + pushdown engines. |
| **Ibis `create_table` in-DB materialization** — write back same DB with zero round-trip | ⬜ | 🔗→🧩 | Small addition to the Ibis engine. |
| **Power BI semantic model read** (XMLA/TMDL/DAX) | ⬜ | 🧩 Plugin | Read feasible; writing cautioned (governance). |
| **StarRocks Stream Load / MySQL LOAD DATA** — best-tier bulk paths | ⬜ | 🔗 in `fast_write` | Optimizes existing dispatcher. |
| **`fast_read`** (ConnectorX Arrow-native fast source reads) | ⬜ | 🔗 in helpers | Symmetric to fast_write. |
| **Desktop app** (Electron/Tauri) — education/free tier | ⬜ | Packaging | Independent track. |

---

## Free vs enterprise: the intended line

**Free (open core):** a complete tool for an individual or small team —
all engines that run locally (pandas/Polars/DuckDB), **all** connectors,
fast_write, reports, profiling, AI authoring, basic cron, self-hosting.

**Enterprise (paid):** operational maturity and scale for organizations —
warehouse pushdown engines (SQL/Ibis), scheduler robustness (retries/alerts/
calendars), auth/SSO/RBAC, the isolated plugin runtime, worker-queue scaling,
and the catalog/MCP layer. The theme: **individuals get a great tool; companies
pay for the things companies need** (security, scale, governance, support).

Connectors are deliberately **never** gated — gating them would just fork the
community, and open connectors are table stakes.

---

## Pre-split work (required before a public/private repo split)

To move from "one embedded codebase" to "open core (public) + enterprise
plugins (private)", in order:

1. **Engine-registry refactor** — replace the `if engine == "sql"/"ibis"`
   branches in `executor.py` with an `ENGINES` dict that plugins extend.
2. **Plugin loader** — discover enterprise packages via Python entry points at
   startup; add `/api/capabilities` so the frontend renders available
   engines/features dynamically.
3. **Extract embedded enterprise code** — move SQL/Ibis engines and the pro
   scheduler features out of core files into an enterprise plugin package.
4. **Licensing library** — Ed25519 sign/verify, offline.
5. **Auth interface** — no-op stub in open core; real impl in enterprise plugin.

Until step 1–3 are done, the clean two-repo model isn't possible; the practical
near-term option is to **launch fully open (everything public under AGPL)** and
extract the private enterprise layer later, once a paying customer justifies it.
