"""Custom (saved) processors API."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import custom_processor_service as svc

router = APIRouter()


class CustomIn(BaseModel):
    name: str
    description: str | None = ""
    engine: str | None = "pandas"
    code: str | None = ""


@router.get("/")
async def list_custom():
    return svc.list_custom()


@router.post("/", status_code=201)
async def create_custom(body: CustomIn):
    return svc.create_custom(body.model_dump())


@router.delete("/{cid}", status_code=204)
async def delete_custom(cid: str):
    if not svc.delete_custom(cid):
        raise HTTPException(404, "Not found")
