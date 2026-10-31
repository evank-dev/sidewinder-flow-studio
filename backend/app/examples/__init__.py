"""Example flows that ship with SFS itself (plugins can add their own through
the registry). The project picker lists them under "Start from an example",
and the desktop welcome screen offers them on first run.

Sample data sits next to this module and is read with importlib.resources, so
the examples work in every install: from source, in Docker, and frozen.
"""
from __future__ import annotations

SALES_CSV = "sales.csv"


def _edge(source: str, target: str) -> dict:
    return {"id": f"e-{source}-{target}", "source": source, "target": target,
            "sourceHandle": "out", "targetHandle": "in"}


def _node(node_id: str, node_type: str, at: tuple[int, int], **data) -> dict:
    return {"id": node_id, "type": node_type, "position": {"x": at[0], "y": at[1]}, "data": data}


LOAD = """\
# Weekly sales of a small school-supplies shop, January to June.
# Sample data shipped with SFS. For your own file:
#   df = pd.read_csv("/path/to/my_data.csv")
from importlib.resources import files

df = pd.read_csv(files("app.examples") / "sales.csv", parse_dates=["date"])
"""

CLEAN = """\
# Fix what's wrong with the raw data, then add the columns we need.
df = df.dropna(subset=["quantity"])                  # 4 rows have no quantity
df["region"] = df["region"].str.title()              # "north" -> "North"
df["quantity"] = df["quantity"].astype(int)
df["revenue"] = df["quantity"] * df["unit_price"]
df["month"] = df["date"].dt.to_period("M").astype(str)
"""

MONTHLY = """\
-- DuckDB SQL runs on the upstream frame, called df.
SELECT month, region, SUM(revenue) AS revenue, SUM(quantity) AS units
FROM df
GROUP BY month, region
ORDER BY month, region
"""

TOP_PRODUCTS = """\
# Polars: df arrives as a LazyFrame.
df = (
    df.group_by("product")
      .agg(pl.col("revenue").sum().round(2), pl.col("quantity").sum().alias("units"))
      .sort("revenue", descending=True)
)
"""

CHART = """\
# Monthly revenue per region. Leave the figure in `result`.
import matplotlib.pyplot as plt

table = df.pivot(index="month", columns="region", values="revenue")
fig, ax = plt.subplots(figsize=(8, 4))
table.plot(kind="bar", ax=ax, width=0.8)
ax.set_xlabel("")
ax.set_ylabel("revenue")
ax.set_title("Monthly revenue by region")
ax.tick_params(axis="x", rotation=0)
fig.tight_layout()
result = fig
"""

SALES_PIPELINE = {
    "name": "Sales pipeline",
    "nodes": [
        _node("start", "trigger", (40, 240), label="Start", run_mode="manual", cron="", timezone="UTC"),
        _node("note", "annotation", (300, 0), color="slate", fontSize=13, text=(
            "A small CSV pipeline: load → clean → summarise, with one engine per step.\n"
            "Click Run Flow, then click any node to see its data. Open a node to read its code.\n"
            "Try: change the SQL to group by product, or open the Explore node to build your own chart.")),
        _node("load", "processor", (300, 240), label="Load sales.csv", engine="pandas", code=LOAD),
        _node("clean", "processor", (620, 240), label="Clean (pandas)", engine="pandas", code=CLEAN),
        _node("monthly", "processor", (940, 120), label="Monthly by region (DuckDB)", engine="duckdb", code=MONTHLY),
        _node("top", "processor", (940, 380), label="Top products (Polars)", engine="polars", code=TOP_PRODUCTS),
        _node("chart", "chart_out", (1260, 60), label="Revenue chart", code=CHART),
        _node("table", "table_out", (1260, 380), label="Top products"),
        _node("explore", "explore_out", (940, 560), label="Explore sales"),
    ],
    "edges": [_edge("start", "load"), _edge("load", "clean"), _edge("clean", "monthly"),
              _edge("clean", "top"), _edge("monthly", "chart"), _edge("top", "table"),
              _edge("clean", "explore")],
}

EXAMPLES = (
    ("Sales pipeline (CSV)",
     "Load a CSV, clean it with pandas, summarise with DuckDB SQL and Polars, then chart and explore it.",
     SALES_PIPELINE),
)


def register() -> None:
    from app.engine.registry import get_example, register_example

    for name, description, flow in EXAMPLES:
        if get_example(name) is None:
            register_example(name=name, description=description, flow=flow, source="builtin")
