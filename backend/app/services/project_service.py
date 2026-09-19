import json, uuid
from datetime import datetime, UTC
from pathlib import Path
from app.core.config import settings


def _dir() -> Path:
    p = Path(settings.PROJECTS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(pid: str) -> Path:
    return _dir() / f"{pid}.json"


def list_projects() -> list[dict]:
    out = []
    for f in sorted(_dir().glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out.append({"id": d["id"], "name": d["name"],
                        "description": d.get("description", ""),
                        "updated_at": d.get("updated_at")})
        except Exception:
            pass
    return out


def get_project(pid: str) -> dict | None:
    p = _path(pid)
    return json.loads(p.read_text()) if p.exists() else None


def create_project(name: str, description: str = "") -> dict:
    pid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    # Default first flow with a Manual trigger node pre-placed
    trigger_id = str(uuid.uuid4())
    data = {
        "id": pid, "name": name, "description": description,
        "created_at": now, "updated_at": now,
        "flows": [{
            "id": str(uuid.uuid4()),
            "name": "Flow 1",
            "active": True,
            "imports": "import pandas as pd\nimport sqlalchemy as sa\n",
            "nodes": [{
                "id": trigger_id,
                "type": "trigger",
                "position": {"x": 80, "y": 200},
                "data": {
                    "label": "Start",
                    "run_mode": "manual",
                    "cron": "",
                    "timezone": "UTC",
                }
            }],
            "edges": [],
        }],
    }
    _path(pid).write_text(json.dumps(data, indent=2))
    return data


def save_project(pid: str, payload: dict) -> dict | None:
    p = _path(pid)
    if not p.exists():
        return None
    existing = json.loads(p.read_text())
    existing.update({
        "flows": payload.get("flows", existing["flows"]),
        "name": payload.get("name", existing["name"]),
        "description": payload.get("description", existing.get("description", "")),
        "updated_at": datetime.now(UTC).isoformat(),
    })
    p.write_text(json.dumps(existing, indent=2))
    return existing


def delete_project(pid: str) -> bool:
    p = _path(pid)
    if not p.exists():
        return False
    p.unlink()
    return True
