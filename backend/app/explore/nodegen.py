"""Explore → flow: turn what the user built in Explore into a processor node.

Two scopes:
    dataset — the source plus the chart's filters, every column (the default:
              the node feeds a flow, which does its own shaping)
    chart   — the chart's own query, aggregation included

and, by source:
    cached (frame / persist) → DuckDB processor over its input `df`
    live (table / sql)       → SQL ⚡ processor running in the connection,
                               or a pandas processor reading the same query
                               through get_engine() (data comes into SFS)
"""
from __future__ import annotations

from app.explore import compiler, live

LIVE_ENGINES = ("sql", "pandas")


def dataset_payload(payload: dict, fields: list[dict]) -> tuple[dict, list[str]]:
    """The chart's filters on source columns, selecting every column.

    Filters on computed fields (bins, date parts) belong to the chart, not the
    data, so they are left out and reported back.
    """
    base = {f["fid"] for f in fields}
    steps, dropped = [], []
    for step in payload.get("workflow", []):
        if step.get("type") != "filter":
            continue
        kept = [f for f in step.get("filters", []) if f.get("fid") in base]
        dropped += [f.get("fid") for f in step.get("filters", []) if f.get("fid") not in base]
        if kept:
            steps.append({"type": "filter", "filters": kept})
    steps.append({"type": "view", "query": [{"op": "raw", "fields": [f["fid"] for f in fields]}]})
    return {"workflow": steps}, dropped


def _pretty_duckdb(sql: str) -> str:
    import sqlglot
    return sqlglot.transpile(sql, read="duckdb", write="duckdb", pretty=True)[0]


def _py_string(text: str) -> str:
    """Python literal for SQL text: a readable triple-quoted block when safe."""
    if '"""' not in text and "\\" not in text and not text.endswith('"'):
        return f'"""\n{text}\n"""'
    return repr(text)


def make_node(kind: str, payload: dict, fields: list[dict], *, mode: str, label: str,
              engine: str | None = None, dialect: str | None = None, connection: str | None = None,
              table: str | None = None, sql: str | None = None, input_hint: str = "") -> dict:
    """Processor node data ({label, engine, code[, target_connection]}) plus notes."""
    if mode not in ("dataset", "chart"):
        raise ValueError(f"Unknown mode '{mode}'")
    notes: list[str] = []
    if mode == "dataset":
        payload, dropped = dataset_payload(payload, fields)
        if dropped:
            notes.append("Filters on computed fields were left out: " + ", ".join(sorted(set(dropped))))
    else:
        payload = {k: v for k, v in payload.items() if k != "limit"}     # the node gets all rows
    what = "the chart's query" if mode == "chart" else "the data behind the chart, with its filters"
    header = f"From Explore: {label} — {what}"

    if kind in ("frame", "persist"):
        body = _pretty_duckdb(compiler.compile(payload, fields, relation="df"))
        code = f"-- {header}\n" + (f"-- Input: {input_hint}\n" if input_hint else "") + body
        return {"node": {"label": f"Explore · {label}", "engine": "duckdb", "code": code}, "notes": notes}

    if engine not in LIVE_ENGINES:
        raise ValueError(f"Pick an engine for a live source: {', '.join(LIVE_ENGINES)}")
    query = live.live_sql(compiler.compile(payload, fields), live.relation_sql(kind, dialect, table=table, sql=sql),
                          dialect, cap=None, pretty=True)
    if engine == "sql":
        code = f"-- {header}\n-- Runs inside {connection} ({dialect}); only the result comes back.\n{query}"
        return {"node": {"label": f"Explore · {label}", "engine": "sql", "code": code,
                         "target_connection": connection}, "notes": notes}
    code = (f"# {header}\n"
            f"# Reads the result into SFS through the {connection} connection.\n"
            f"sql = {_py_string(query)}\n"
            f"df = pd.read_sql(sql, get_engine({connection!r}))\n")
    return {"node": {"label": f"Explore · {label}", "engine": "pandas", "code": code}, "notes": notes}
