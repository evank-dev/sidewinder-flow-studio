"""Explore API — Graphic Walker server-side computation (Phase 0 spike).

    GET  /api/explore/schema  ?kind=frame&project_id=…&node_id=…   or   ?kind=table&connection=…&table=…
    POST /api/explore/query   { source: {...}, payload: <GW DSL> }
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.engine.executor import SQLGLOT_DIALECTS
from app.explore import sources
from app.explore.compiler import CompileError
from app.services.connection_service import connection_maps, list_connections

router = APIRouter()


class Source(BaseModel):
    kind: str                       # frame | table
    project_id: str | None = None
    node_id: str | None = None
    connection: str | None = None
    table: str | None = None


class QueryIn(BaseModel):
    source: Source
    payload: dict


async def _engine(db: AsyncSession, name: str):
    """SQLAlchemy engine + SQLGlot dialect for a named SFS connection."""
    import sqlalchemy as sa
    maps = connection_maps(await list_connections(db))
    if name not in maps["urls"]:
        raise HTTPException(404, f"Connection '{name}' not found")
    if name in maps["broken"]:
        raise HTTPException(400, maps["broken"][name])
    dialect = maps["dialects"][name]
    eng = sa.create_engine(maps["urls"][name], connect_args=maps["cargs"].get(name) or {})
    return eng, SQLGLOT_DIALECTS.get(dialect, dialect)


@router.get("/schema")
async def schema(kind: str, project_id: str | None = None, node_id: str | None = None,
                 connection: str | None = None, table: str | None = None,
                 db: AsyncSession = Depends(get_db)):
    try:
        if kind == "frame":
            return {"fields": await run_in_threadpool(sources.frame_schema, project_id, node_id)}
        if kind == "table":
            eng, _ = await _engine(db, connection)
            try:
                return {"fields": await run_in_threadpool(sources.table_schema, eng, table)}
            finally:
                eng.dispose()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    raise HTTPException(400, f"Unknown source kind '{kind}'")


@router.post("/query")
async def query(body: QueryIn, db: AsyncSession = Depends(get_db)):
    s = body.source
    try:
        if s.kind == "frame":
            r = await run_in_threadpool(sources.frame_query, s.project_id, s.node_id, body.payload)
        elif s.kind == "table":
            eng, dialect = await _engine(db, s.connection)
            try:
                r = await run_in_threadpool(sources.table_query, eng, dialect, s.table, body.payload)
            finally:
                eng.dispose()
        else:
            raise HTTPException(400, f"Unknown source kind '{s.kind}'")
    except CompileError as exc:
        raise HTTPException(422, f"Could not compile chart query: {exc}")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        # Database errors (bad column, type mismatch, timeout) are the user's
        # chart, not a server fault — return the message, not a bare 500.
        raise HTTPException(400, f"Query failed: {str(exc).splitlines()[0][:500]}")
    return {"rows": r.rows, "sql": r.sql, "truncated": r.truncated,
            "compile_ms": round(r.compile_ms, 2), "exec_ms": round(r.exec_ms, 1)}
