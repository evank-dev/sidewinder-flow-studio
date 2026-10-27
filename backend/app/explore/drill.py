"""Drill-through: from a point on a chart over cached data to the detail rows
behind it, in a live table.

A cached source (frame / persist) declares a detail source explicitly:

    {"connection": "clickhouse_local", "table": "default.trips",
     "keys": [{"field": "payment_type", "column": "payment_type"}, ...]}

Drilling on a chart point turns that point's dimension values, plus the
chart's filters, into conditions on the mapped key columns and runs
SELECT * FROM <table> WHERE … under the live guardrails. Fields without a key
mapping are reported, never guessed. Nothing is routed automatically.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings

DETAIL_ROWS = 1000          # rows shown in the drill panel; "Explore these rows" has no such cap
_lock = threading.Lock()


class DrillError(ValueError):
    pass


# ── settings (one JSON file next to the projects) ─────────────────────────────

def _store() -> Path:
    # A dot-file: project_service lists *.json in this directory as projects.
    return Path(settings.PROJECTS_DIR) / ".explore_drill.json"


def _read() -> dict:
    try:
        return json.loads(_store().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def get_config(key: str) -> dict | None:
    return _read().get(key)


def set_config(key: str, config: dict | None) -> dict | None:
    if config is not None:
        keys = [k for k in config.get("keys") or [] if k.get("field") and k.get("column")]
        if not config.get("connection") or not config.get("table"):
            raise DrillError("Pick a connection and a detail table")
        if not keys:
            raise DrillError("Map at least one field to a column of the detail table")
        config = {"connection": config["connection"], "table": config["table"],
                  "keys": [{"field": k["field"], "column": k["column"]} for k in keys]}
    with _lock:
        data = _read()
        if config is None:
            data.pop(key, None)
        else:
            data[key] = config
        path = _store()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
    return config


# ── conditions ────────────────────────────────────────────────────────────────

def conditions(payload: dict, row: dict, fields: list[dict]) -> list[tuple[str, str, object]]:
    """(field, op, value) from the clicked point and the chart's filters.

    ops: eq, in, not_in, between, time_between (epoch-ms bounds). Only source
    columns count; computed fields (bins, date parts) have no detail column.
    """
    base = {f["fid"] for f in fields}
    out: list[tuple[str, str, object]] = []
    for fid, value in row.items():
        if fid in base:
            out.append((fid, "eq", value))
    for step in payload.get("workflow", []):
        if step.get("type") != "filter":
            continue
        for f in step.get("filters", []):
            fid, rule = f.get("fid"), f.get("rule") or {}
            if fid not in base:
                continue
            kind, value = rule.get("type"), rule.get("value")
            if kind == "one of":
                out.append((fid, "in", list(value or [])))
            elif kind == "not in":
                out.append((fid, "not_in", list(value or [])))
            elif kind == "range":
                out.append((fid, "between", value))
            elif kind == "temporal range":
                out.append((fid, "time_between", value))
    return out


def _literal(value, temporal: bool):
    from sqlglot import exp

    if value is None:
        return exp.null()
    if isinstance(value, bool):
        return exp.Boolean(this=value)
    if isinstance(value, (int, float)):
        if temporal:                               # epoch ms from Graphic Walker
            return _ms(value)
        return exp.Literal.number(value)
    if temporal:
        return exp.cast(exp.Literal.string(str(value).replace("T", " ").rstrip("Z")),
                        exp.DataType.build("TIMESTAMP(3)", dialect="duckdb"))
    return exp.Literal.string(str(value))


def _ms(ms):
    from sqlglot import exp
    t = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(ms))
    return exp.cast(exp.Literal.string(t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]),
                    exp.DataType.build("TIMESTAMP(3)", dialect="duckdb"))


def detail_sql(conds: list[tuple[str, str, object]], config: dict, fields: list[dict],
               dialect: str) -> tuple[str | None, list[str], list[str]]:
    """(SELECT * FROM detail WHERE …, applied, unmapped) in the target dialect."""
    from sqlglot import exp

    keys = {k["field"]: k["column"] for k in config["keys"]}
    temporal = {f["fid"] for f in fields if f.get("semanticType") == "temporal"}
    where, applied, unmapped = [], [], []
    for fid, op, value in conds:
        col = keys.get(fid)
        if not col:
            unmapped.append(fid)
            continue
        c = exp.column(col, quoted=True)
        t = fid in temporal
        if op == "eq":
            where.append(c.is_(exp.null()) if value is None else c.eq(_literal(value, t)))
        elif op in ("in", "not_in") and value:
            cond = c.isin(*[_literal(v, t) for v in value])
            where.append(exp.not_(cond) if op == "not_in" else cond)
        elif op == "between" and value and len(value) == 2:
            where.append(exp.Between(this=c, low=_literal(value[0], t), high=_literal(value[1], t)))
        elif op == "time_between" and value and len(value) == 2:
            where.append(exp.Between(this=c, low=_ms(value[0]), high=_ms(value[1])))
        else:
            continue
        applied.append(f"{fid} → {col}")
    if not where:
        return None, applied, sorted(set(unmapped))
    q = exp.select("*").from_(exp.to_table(config["table"], dialect=dialect)).where(exp.and_(*where))
    return q.sql(dialect=dialect), applied, sorted(set(unmapped))


def run_drill(engine, dialect: str, config: dict, payload: dict, row: dict, fields: list[dict],
              timeout: float | None = None) -> dict:
    from app.explore import live

    sql, applied, unmapped = detail_sql(conditions(payload, row, fields), config, fields, dialect)
    if not sql:
        raise DrillError("None of this point's fields are mapped to a detail column"
                         + (f" (unmapped: {', '.join(unmapped)})" if unmapped else ""))
    from sqlglot import exp
    import sqlglot
    capped = exp.select("*").from_(sqlglot.parse_one(sql, read=dialect).subquery("sfs_detail")) \
        .limit(DETAIL_ROWS + 1).sql(dialect=dialect)
    rows = live._execute(engine, dialect, capped, timeout or settings.EXPLORE_TIMEOUT_S)
    return {"rows": rows[:DETAIL_ROWS], "truncated": len(rows) > DETAIL_ROWS, "sql": sql,
            "applied": applied, "unmapped": unmapped, "connection": config["connection"], "dialect": dialect}
