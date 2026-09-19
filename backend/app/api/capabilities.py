"""
Capabilities API — what this SFS instance can do.

The frontend calls this to render available engines (including any added by
plugins) instead of hard-coding a list, so installing a plugin surfaces its
engine in the UI without a frontend change.
"""
import importlib.util

from fastapi import APIRouter

from app.engine import executor as _executor  # noqa: F401 — registers builtins
from app.engine.registry import list_engines, loaded_plugins

router = APIRouter()


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


@router.get("/")
async def get_capabilities():
    engines = list_engines()
    return {
        "engines": engines,
        "plugins": loaded_plugins(),
        "features": {
            # Optional capabilities the UI can gate on
            "enterprise_engines": any(
                e["tier"] == "enterprise" and e["available"] for e in engines
            ),
            "reports": _has("duckdb"),
            "iceberg": _has("pyiceberg"),
            "deltalake": _has("deltalake"),
        },
    }
