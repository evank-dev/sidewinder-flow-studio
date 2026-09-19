import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services import connection_service

router = APIRouter()


class ConnectionIn(BaseModel):
    name: str
    dialect: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    extra_params: dict | None = None


def _out(c) -> dict:
    return {
        "id": c.id, "name": c.name, "dialect": c.dialect,
        "host": c.host, "port": c.port, "database": c.database, "username": c.username,
        "extra_params": json.loads(c.extra_params) if c.extra_params else None,
    }


@router.get("/")
async def list_connections(db: AsyncSession = Depends(get_db)):
    return [_out(c) for c in await connection_service.list_connections(db)]


@router.post("/", status_code=201)
async def create_connection(body: ConnectionIn, db: AsyncSession = Depends(get_db)):
    return _out(await connection_service.create_connection(db, body.model_dump()))


class ConnectionUpdate(BaseModel):
    name: str | None = None
    dialect: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None       # blank/omitted keeps the existing password
    extra_params: dict | None = None


@router.put("/{cid}")
async def update_connection(cid: str, body: ConnectionUpdate, db: AsyncSession = Depends(get_db)):
    c = await connection_service.update_connection(db, cid, body.model_dump(exclude_unset=True))
    if not c:
        raise HTTPException(404, "Not found")
    return _out(c)


@router.delete("/{cid}", status_code=204)
async def delete_connection(cid: str, db: AsyncSession = Depends(get_db)):
    if not await connection_service.delete_connection(db, cid):
        raise HTTPException(404, "Not found")


@router.post("/{cid}/test")
async def test_connection(cid: str, db: AsyncSession = Depends(get_db)):
    c = await connection_service.get_connection(db, cid)
    if not c:
        raise HTTPException(404, "Not found")
    return await connection_service.test_connection(c)
