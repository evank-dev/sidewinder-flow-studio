"""
Frame cache — stores Arrow IPC tables on disk between node executions.

Keyed by (flow_id, node_id).  Using Arrow IPC gives us:
  - Fast read/write (~1 GB/s)
  - Lossless type preservation
  - Compact columnar storage
  - Direct conversion to/from pandas with zero copy

Future: swap disk-backed store for in-memory dict when running
interactively, keep disk for scheduled / long-running flows.
"""
import pyarrow as pa
import pyarrow.ipc as ipc
import pandas as pd
from pathlib import Path

from app.core.config import settings


def _cache_path(flow_id: str, node_id: str) -> Path:
    base = Path(settings.FRAME_CACHE_DIR) / flow_id
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{node_id}.arrow"


def store_frame(flow_id: str, node_id: str, df: pd.DataFrame) -> int:
    """Persist a DataFrame as Arrow IPC. Returns row count."""
    table = pa.Table.from_pandas(df, preserve_index=False)
    path = _cache_path(flow_id, node_id)
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)
    return len(table)


def load_frame(flow_id: str, node_id: str) -> pd.DataFrame:
    """Load a cached Arrow IPC file back to a DataFrame."""
    path = _cache_path(flow_id, node_id)
    if not path.exists():
        raise FileNotFoundError(f"No cached frame for node {node_id} in flow {flow_id}")
    with ipc.open_file(str(path)) as reader:
        return reader.read_all().to_pandas()


def load_frame_arrow(flow_id: str, node_id: str) -> pa.Table:
    """Load a cached frame as a pyarrow Table — no pandas conversion.
    Used by the DuckDB engine, which queries Arrow directly (zero-copy)."""
    path = _cache_path(flow_id, node_id)
    if not path.exists():
        raise FileNotFoundError(f"No cached frame for node {node_id} in flow {flow_id}")
    with ipc.open_file(str(path)) as reader:
        return reader.read_all()


def store_frame_arrow(flow_id: str, node_id: str, table: pa.Table) -> int:
    """Persist a pyarrow Table directly — no pandas conversion.
    Used by the DuckDB engine to write results straight back to the cache."""
    path = _cache_path(flow_id, node_id)
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)
    return len(table)


def has_frame(flow_id: str, node_id: str) -> bool:
    return _cache_path(flow_id, node_id).exists()


def frame_path(flow_id: str, node_id: str) -> str:
    """Filesystem path of a cached Arrow IPC frame — used by the Polars engine
    to pl.scan_ipc() lazily, so large frames never fully load until collect()."""
    path = _cache_path(flow_id, node_id)
    if not path.exists():
        raise FileNotFoundError(f"No cached frame for node {node_id} in flow {flow_id}")
    return str(path)


def clear_flow_cache(flow_id: str):
    """Remove all cached frames for a flow (e.g. on re-run from root)."""
    base = Path(settings.FRAME_CACHE_DIR) / flow_id
    if base.exists():
        for f in base.glob("*.arrow"):
            f.unlink()


def get_frame_meta(flow_id: str, node_id: str) -> dict | None:
    """Return {rows, columns, size_bytes} without loading full frame."""
    path = _cache_path(flow_id, node_id)
    if not path.exists():
        return None
    with ipc.open_file(str(path)) as reader:
        schema = reader.schema_arrow
        rows = sum(reader.get_batch(i).num_rows for i in range(reader.num_record_batches))
    return {
        "rows": rows,
        "columns": len(schema),
        "column_names": schema.names,
        "size_bytes": path.stat().st_size,
    }
