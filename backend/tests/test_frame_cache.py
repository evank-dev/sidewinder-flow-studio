"""Frame cache metadata and the Output panel's frame preview endpoint."""
import pyarrow as pa
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import execute as execute_api
from app.core import frame_cache
from app.core.config import settings


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "FRAME_CACHE_DIR", str(tmp_path))
    # Several record batches, so the preview has to stop early.
    batches = [pa.record_batch({"i": list(range(k * 100, k * 100 + 100)), "s": ["x"] * 100}) for k in range(5)]
    frame_cache.store_frame_arrow("p", "n", pa.Table.from_batches(batches))


def test_frame_meta(cache):
    assert frame_cache.get_frame_meta("p", "n") == {
        "rows": 500, "columns": 2, "column_names": ["i", "s"],
        "size_bytes": frame_cache._cache_path("p", "n").stat().st_size}
    assert frame_cache.get_frame_meta("p", "missing") is None


def test_head_reads_only_what_it_shows(cache):
    df = frame_cache.load_frame_head("p", "n", 150)
    assert len(df) == 150 and df["i"].tolist() == list(range(150))
    assert len(frame_cache.load_frame_head("p", "n", 10_000)) == 500


def test_inspect_endpoint(cache):
    app = FastAPI()
    app.include_router(execute_api.router, prefix="/api/execute")
    d = TestClient(app).get("/api/execute/frame/p/n", params={"limit": 3}).json()
    assert d["total"] == 500 and [r["i"] for r in d["rows"]] == [0, 1, 2]
    assert [c["name"] for c in d["schema"]] == ["i", "s"] and d["schema"][0]["dtype"] == "int64"
