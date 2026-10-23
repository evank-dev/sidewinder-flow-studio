"""AI notes → processors (build-flow), with the model replaced by a stand-in.

Covers everything around the LLM call: topological order, which system prompt
each note gets, the spec and connection list in the request, and how declared
or parsed output columns flow into the next note's context.
"""
import asyncio
from types import SimpleNamespace

import pytest

from app.api import agent as agent_api
from app.services import agent_service, connection_service


def _flow():
    n = lambda i, t, d: {"id": i, "type": t, "data": d}
    e = lambda a, b: {"source": a, "target": b}
    return {"nodes": [
        n("trg", "trigger", {"label": "Start"}),
        n("end", "ai_end", {"label": "Load", "target_mode": "db", "connection": "clickhouse_local",
                            "table": "default.salary_by_dept", "write_mode": "replace"}),
        n("step", "ai_step", {"label": "Avg salary", "logic": "average current salary per department",
                              "output_columns": "dept_name, avg_salary"}),
        n("src", "ai_start", {"label": "Employees", "source_mode": "sql", "connection": "postgres_local",
                              "sql": "SELECT * FROM employees.salary"}),
    ], "edges": [e("trg", "src"), e("src", "step"), e("step", "end")]}


@pytest.fixture
def stand_in(monkeypatch):
    calls = []

    async def fake_generate(request, node_type, db=None, system_override=None, **_):
        calls.append({"request": request, "system": system_override})
        code = {0: "df = pd.read_sql('SELECT * FROM employees.salary', get_engine('postgres_local'))\n"
                   "# OUTPUT_COLUMNS: employee_id, amount, from_date, to_date",
                1: "df = df.groupby('dept_name', as_index=False)['amount'].mean()",
                2: "fast_write(df, 'clickhouse_local', 'default.salary_by_dept', mode='replace')"}[len(calls) - 1]
        return {"code": code, "error": None, "provider": "stand-in"}

    async def fake_conns(db):
        return [SimpleNamespace(name="postgres_local", dialect="postgresql"),
                SimpleNamespace(name="clickhouse_local", dialect="clickhouse")]

    monkeypatch.setattr(agent_service, "generate_code", fake_generate)
    monkeypatch.setattr(connection_service, "list_connections", fake_conns)
    return calls


def _build(flow):
    return asyncio.run(agent_api.build_flow(agent_api.BuildFlowRequest(flow_state=flow), db=None))


def test_notes_compiled_in_dag_order_with_right_prompts(stand_in):
    out = _build(_flow())
    assert out["errors"] == []
    assert [b["node_id"] for b in out["nodes"]] == ["src", "step", "end"]
    assert [c["system"] for c in stand_in] == [agent_service.FLOW_SOURCE_SYSTEM_PROMPT,
                                              agent_service.FLOW_STEP_SYSTEM_PROMPT,
                                              agent_service.FLOW_SINK_SYSTEM_PROMPT]
    assert all(b["provider"] == "stand-in" and b["code"] for b in out["nodes"])


def test_request_carries_connections_and_spec(stand_in):
    _build(_flow())
    first = stand_in[0]["request"]
    assert "postgres_local (postgresql)" in first and "clickhouse_local (clickhouse)" in first
    assert "SELECT * FROM employees.salary" in first
    assert "Upstream output columns: unknown" in first


def test_columns_thread_downstream(stand_in):
    _build(_flow())
    # parsed from the source's OUTPUT_COLUMNS line
    assert "employee_id, amount, from_date, to_date" in stand_in[1]["request"]
    # declared on the step note beats whatever the code says
    assert "dept_name, avg_salary" in stand_in[2]["request"]


def test_generation_failure_is_reported_per_node(monkeypatch, stand_in):
    async def failing(request, node_type, db=None, system_override=None, **_):
        return {"code": None, "error": "No AI provider configured.", "provider": None}
    monkeypatch.setattr(agent_service, "generate_code", failing)
    out = _build(_flow())
    assert out["nodes"] == [] and {e["node_id"] for e in out["errors"]} == {"src", "step", "end"}


def test_flow_without_notes():
    flow = {"nodes": [{"id": "t", "type": "trigger", "data": {}}], "edges": []}
    assert _build(flow) == {"nodes": [], "error": "No AI notes found in this flow."}
