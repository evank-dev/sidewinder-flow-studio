"""Run history / audit API."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.run_history import RunHistory

router = APIRouter()


@router.get("/")
async def list_runs(project_id: str | None = None, limit: int = 50,
                    db: AsyncSession = Depends(get_db)):
    q = select(RunHistory).order_by(RunHistory.started_at.desc()).limit(min(limit, 200))
    if project_id:
        q = q.where(RunHistory.project_id == project_id)
    rows = (await db.execute(q)).scalars().all()
    return [{
        "id": r.id, "flow_id": r.flow_id, "flow_name": r.flow_name,
        "trigger": r.trigger, "status": r.status, "attempt": r.attempt,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "duration_ms": r.duration_ms, "nodes_ok": r.nodes_ok,
        "nodes_error": r.nodes_error, "error": r.error,
    } for r in rows]
