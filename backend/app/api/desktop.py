"""Desktop edition only: where the user's data lives, first-run state, logs.

Mounted at /api/desktop when SFS_DESKTOP=1 (app/desktop.py sets it). The
backend runs on the user's own machine there, so it can also open a folder in
the system file manager; only the fixed folders below, never a path from the
request.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

WELCOME_MARKER = ".welcome_seen"
LOG_TAIL_BYTES = 200_000


def data_dir() -> Path:
    return Path(os.environ["SFS_DATA_DIR"])


def _folders() -> dict[str, Path]:
    d = data_dir()
    return {"data": d, "projects": Path(os.environ.get("PROJECTS_DIR", d / "projects")), "logs": d / "logs"}


def _logs() -> list[dict]:
    logs = _folders()["logs"]
    if not logs.is_dir():
        return []
    return [{"name": p.name, "size": p.stat().st_size}
            for p in sorted(logs.iterdir()) if p.is_file() and p.suffix in (".log", ".1")]


@router.get("/")
def info(request: Request):
    d = data_dir()
    folders = _folders()
    return {
        "version": request.app.version,
        "data_dir": str(d),
        "projects_dir": str(folders["projects"]),
        "logs_dir": str(folders["logs"]),
        "secret_key": str(d / "secret.key"),
        "database": str(d / "flow_studio.db"),
        "logs": _logs(),
        "welcome_seen": (d / WELCOME_MARKER).exists(),
    }


@router.post("/welcome-seen", status_code=204)
def welcome_seen():
    (data_dir() / WELCOME_MARKER).touch()


@router.delete("/welcome-seen", status_code=204)
def welcome_again():
    (data_dir() / WELCOME_MARKER).unlink(missing_ok=True)


@router.get("/logs/{name}")
def read_log(name: str):
    """The end of one log file, by name from info()['logs'] (no paths)."""
    if name not in {log["name"] for log in _logs()}:
        raise HTTPException(404, f"No log named '{name}'")
    path = _folders()["logs"] / name
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - LOG_TAIL_BYTES))
        text = f.read().decode("utf-8", errors="replace")
    return {"name": name, "size": size, "truncated": size > LOG_TAIL_BYTES, "text": text}


class OpenIn(BaseModel):
    folder: str          # data | projects | logs


def _launch_environment() -> dict[str, str]:
    """The environment for a program we start (the file manager): without
    what our own packaging changed. PyInstaller points LD_LIBRARY_PATH at the
    bundle (keeping the original as LD_LIBRARY_PATH_ORIG), and an AppImage
    prepends its mount ($APPDIR) to many search paths; either would make the
    file manager load our libraries instead of the system's."""
    env = dict(os.environ)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    appdir = env.get("APPDIR", "").rstrip("/")
    if appdir:
        for key, value in list(env.items()):
            if appdir in value:
                kept = [p for p in value.split(os.pathsep) if p and not p.startswith(appdir)]
                if kept:
                    env[key] = os.pathsep.join(kept)
                else:
                    del env[key]
    return env


@router.post("/open", status_code=204)
def open_folder(body: OpenIn):
    folders = _folders()
    if body.folder not in folders:
        raise HTTPException(400, f"Unknown folder '{body.folder}'")
    path = folders[body.folder]
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(path)                                   # noqa: S606 — fixed folder
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(path)], env=_launch_environment(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise HTTPException(500, f"Could not open {path}: {exc}")
