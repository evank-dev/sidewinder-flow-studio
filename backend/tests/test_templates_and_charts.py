"""Plugin chart templates (registry contract) and multi-input Chart nodes."""
import pandas as pd
import pytest

from app.engine import registry
from app.engine.executor import render_chart


@pytest.fixture
def clean_templates(monkeypatch):
    monkeypatch.setattr(registry, "TEMPLATES", [])


def test_plugin_registers_a_chart_template(clean_templates):
    api = registry.RegistryAPI(source="plugin:demo")
    api.register_template(kind="chart", name="Demo plot", code="df.plot()", description="d")
    assert registry.list_templates("chart") == [
        {"kind": "chart", "name": "Demo plot", "code": "df.plot()", "description": "d",
         "source": "plugin:demo"}]
    assert registry.list_templates("other") == []


def test_duplicate_template_is_ignored(clean_templates):
    api = registry.RegistryAPI(source="plugin:a")
    api.register_template(kind="chart", name="Same", code="1")
    registry.RegistryAPI(source="plugin:b").register_template(kind="chart", name="Same", code="2")
    assert [t["code"] for t in registry.list_templates()] == ["1"]


def test_unknown_template_kind_is_refused(clean_templates):
    with pytest.raises(ValueError, match="Unknown template kind 'chrat'"):
        registry.RegistryAPI(source="plugin:a").register_template(kind="chrat", name="x", code="")


def test_chart_gets_every_input():
    a, b = pd.DataFrame({"x": [1, 2]}), pd.DataFrame({"y": [3, 4, 5]})
    code = "result = {'n': [len(f) for f in dfs], 'df2': list(df2.columns)}"
    out = render_chart(a, code, {}, [b])
    assert out["chart_type"] == "echarts" and '"n": [2, 3]' in out["payload"] and '"df2": ["y"]' in out["payload"]


def test_single_input_chart_still_has_dfs():
    out = render_chart(pd.DataFrame({"x": [1]}), "result = {'n': len(dfs)}", {})
    assert '"n": 1' in out["payload"]
