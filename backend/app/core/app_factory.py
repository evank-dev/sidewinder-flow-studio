import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from app.core.config import settings
from app.core.database import init_db
from app.scheduler.scheduler import start_scheduler, stop_scheduler
from app.api import projects, connections, execute, metadata, ws, agent, runs, custom_processors, capabilities


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all data directories exist before anything writes to them.
    # Makes startup robust regardless of Docker/local/env-var overrides.
    from pathlib import Path as _P
    for _p in [
        settings.PROJECTS_DIR,
        settings.FRAME_CACHE_DIR,
        settings.REPORTS_DIR,
        str(_P(settings.PERSIST_DB).parent),
    ]:
        try:
            _P(_p).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    # Discover third-party/enterprise engine plugins (entry point group
    # "sfs.plugins"). A failing plugin is logged and skipped, never fatal.
    try:
        from app.engine import executor as _executor  # registers builtin engines
        from app.engine.registry import load_plugins
        load_plugins()
    except Exception as _exc:
        import logging; logging.getLogger("sfs").error("Plugin load failed: %s", _exc)

    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sidewinder Flow Studio API",
        version="1.10",
        description="Visual Python notebook DAG with scheduling",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects.router,    prefix="/api/projects",    tags=["projects"])
    app.include_router(connections.router, prefix="/api/connections", tags=["connections"])
    app.include_router(execute.router,     prefix="/api/execute",     tags=["execute"])
    app.include_router(metadata.router,    prefix="/api/metadata",    tags=["metadata"])
    app.include_router(agent.router,       prefix="/api/agent",       tags=["agent"])
    app.include_router(runs.router,        prefix="/api/runs",        tags=["runs"])
    app.include_router(custom_processors.router, prefix="/api/custom-processors", tags=["custom"])
    app.include_router(capabilities.router, prefix="/api/capabilities", tags=["capabilities"])
    app.include_router(ws.router,          prefix="/ws",              tags=["websocket"])

    # Single-container mode: serve built React as static files
    static_dir = Path(__file__).parent.parent / "static"
    if os.getenv("SERVE_STATIC", "false").lower() == "true" and static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            return FileResponse(str(static_dir / "index.html"))

    return app
