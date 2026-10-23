"""DuckDB query result → pyarrow.Table, across DuckDB versions.

The Arrow fetch API has changed twice: 1.x has `.arrow()` (a Table, or from
1.5 a streaming RecordBatchReader) and `.fetch_arrow_table()`; 2.0 removed
both in favour of `.to_arrow_table()`. Use this instead of calling any of
them directly.
"""
import pyarrow as pa


def result_to_arrow(result) -> pa.Table:
    for name in ("to_arrow_table", "fetch_arrow_table", "arrow"):
        fn = getattr(result, name, None)
        if fn is not None:
            out = fn()
            return out if isinstance(out, pa.Table) else out.read_all()
    raise TypeError(f"Cannot fetch Arrow from {type(result).__name__}")
