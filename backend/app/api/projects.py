"""Projects API."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services import project_service
from app.scheduler.scheduler import register_flow, unregister_flow, get_next_run

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectSave(BaseModel):
    flows: list[dict]
    name: str | None = None
    description: str | None = None


@router.get("/")
def list_projects():
    return project_service.list_projects()


@router.post("/", status_code=201)
def create_project(body: ProjectCreate):
    return project_service.create_project(body.name, body.description)


@router.get("/{pid}")
def get_project(pid: str):
    p = project_service.get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    # Attach next_run info per flow
    for flow in p.get("flows", []):
        flow["next_run"] = get_next_run(flow["id"])
    return p


@router.put("/{pid}")
def save_project(pid: str, body: ProjectSave):
    result = project_service.save_project(pid, body.model_dump(exclude_none=True))
    if not result:
        raise HTTPException(404, "Project not found")
    # Re-register schedulers for flows that have cron triggers
    for flow in result.get("flows", []):
        trigger_node = next(
            (n for n in flow.get("nodes", []) if n["type"] == "trigger"),
            None,
        )
        if trigger_node:
            td = trigger_node.get("data", {})
            if td.get("run_mode") == "schedule" and td.get("cron") and flow.get("active"):
                register_flow(flow["id"], pid, td["cron"], td.get("timezone", "UTC"))
            else:
                unregister_flow(flow["id"])
    return result


@router.delete("/{pid}", status_code=204)
def delete_project(pid: str):
    if not project_service.delete_project(pid):
        raise HTTPException(404, "Project not found")
