"""Explore API — Graphic Walker server-side computation.

    GET  /api/explore/sources                cached frames, persisted tables, connections
    GET  /api/explore/tables  ?connection=…  schemas, tables and views of a live connection
    GET  /api/explore/schema  ?kind=frame&project_id=…&node_id=…
                              ?kind=persist&table=…
                              ?kind=table&connection=…&table=…
                              ?kind=sql&connection=…&sql=…
    POST /api/explore/query   { source: {...}, payload: <GW DSL> }
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.engine.executor import SQLGLOT_DIALECTS
from app.explore import live, sources
from app.explore.compiler import CompileError
from app.services.connection_service import connection_maps, list_connections

router = APIRouter()

LIVE = ("table", "sql")


class Source(BaseModel):
    kind: str                       # frame | persist | table | sql
    project_id: str | None = None
    node_id: str | None = None
    connection: str | None = None
    table: str | None = None        # persist: table name; table: [schema.]table
    sql: str | None = None          # sql: a SELECT in the connection's dialect

    def cached(self) -> dict:
        return {"project_id": self.project_id, "node_id": self.node_id} if self.kind == "frame" \
            else {"table": self.table}

    def live(self) -> dict:
        return {"table": self.table} if self.kind == "table" else {"sql": self.sql}


class QueryIn(BaseModel):
    source: Source
    payload: dict


async def _engine(db: AsyncSession, name: str | None):
    """Pooled SQLAlchemy engine + SQLGlot dialect for a named SFS connection."""
    maps = connection_maps(await list_connections(db))
    if not name or name not in maps["urls"]:
        raise HTTPException(404, f"Connection '{name}' not found")
    if name in maps["broken"]:
        raise HTTPException(400, maps["broken"][name])
    dialect = maps["dialects"][name]
    eng = live.engine_for(name, maps["urls"][name], maps["cargs"].get(name))
    return eng, SQLGLOT_DIALECTS.get(dialect, dialect)


# A chart sends a query per interaction, and the compiler needs column types.
# Re-reading the catalog (or re-sampling a SQL source) each time is wasted work,
# so live schemas are kept briefly.
_SCHEMA_TTL_S = 60
_schemas: dict[tuple, tuple[float, dict]] = {}


def _live_schema(eng, dialect: str, s: Source) -> dict:
    key = (s.connection, s.kind, s.table, s.sql)
    hit = _schemas.get(key)
    if hit and time.monotonic() - hit[0] < _SCHEMA_TTL_S:
        return hit[1]
    out = live.live_schema(eng, dialect, s.kind, **s.live())
    _schemas[key] = (time.monotonic(), out)
    return out


def _db_error(prefix: str, exc: Exception) -> HTTPException:
    # Database errors (bad column, missing table, credentials) are about the
    # source or the chart, not a server fault: return the message, not a 500.
    return HTTPException(400, f"{prefix}: {str(exc).strip().splitlines()[0][:500]}")


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    out = await run_in_threadpool(sources.list_cached)
    # Names and dialects only — credentials never leave the connection service.
    out["connections"] = [{"name": c.name, "dialect": c.dialect} for c in await list_connections(db)]
    return out


@router.get("/tables")
async def list_tables(connection: str, db: AsyncSession = Depends(get_db)):
    eng, dialect = await _engine(db, connection)
    try:
        return await run_in_threadpool(live.list_tables, eng, dialect)
    except Exception as exc:
        raise _db_error(f"Could not list tables on {connection}", exc)


@router.get("/schema")
async def schema(kind: str, project_id: str | None = None, node_id: str | None = None,
                 connection: str | None = None, table: str | None = None, sql: str | None = None,
                 db: AsyncSession = Depends(get_db)):
    s = Source(kind=kind, project_id=project_id, node_id=node_id, connection=connection, table=table, sql=sql)
    try:
        if kind in ("frame", "persist"):
            return await run_in_threadpool(sources.cached_schema, kind, **s.cached())
        if kind in LIVE:
            eng, dialect = await _engine(db, connection)
            _schemas.pop((s.connection, s.kind, s.table, s.sql), None)     # opening a source re-reads it
            return await run_in_threadpool(_live_schema, eng, dialect, s)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except live.SourceError as exc:
        raise HTTPException(400, str(exc))
    except sources.QueryTimeout as exc:
        raise HTTPException(408, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_error("Could not read schema", exc)
    raise HTTPException(400, f"Unknown source kind '{kind}'")


@router.post("/query")
async def query(body: QueryIn, db: AsyncSession = Depends(get_db)):
    s = body.source
    dialect = "duckdb"
    try:
        if s.kind in ("frame", "persist"):
            r = await run_in_threadpool(lambda: sources.cached_query(s.kind, body.payload, **s.cached()))
        elif s.kind in LIVE:
            eng, dialect = await _engine(db, s.connection)

            def run():
                fields = _live_schema(eng, dialect, s)["fields"]
                return live.live_query(eng, dialect, s.kind, body.payload, fields, **s.live())
            r = await run_in_threadpool(run)
        else:
            raise HTTPException(400, f"Unknown source kind '{s.kind}'")
    except CompileError as exc:
        raise HTTPException(422, f"Could not compile chart query: {exc}")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except live.SourceError as exc:
        raise HTTPException(400, str(exc))
    except sources.QueryTimeout as exc:
        raise HTTPException(408, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_error("Query failed", exc)
    return {"rows": r.rows, "sql": r.sql, "truncated": r.truncated, "row_cap": settings.EXPLORE_ROW_CAP,
            "dialect": dialect, "compile_ms": round(r.compile_ms, 2), "exec_ms": round(r.exec_ms, 1)}
