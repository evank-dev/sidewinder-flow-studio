"""Smoke test for the frozen desktop backend (dist/sfs-backend/).

    python smoke_test.py dist/sfs-backend/sfs-backend[.exe]

Starts the executable the way the desktop shell does, waits for the readiness
line, then checks what can only break in a frozen build: the frontend is
served, every bundled engine is available, a flow runs through pandas, DuckDB,
Polars and the SQL engine (SQLGlot, on SQLite), and Explore compiles a chart
query (the wasmtime native library). Finally it closes stdin, as the shell does
on exit, and expects the backend to stop. Standard library only, so CI can run
it with any Python.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

READY_TIMEOUT = 180          # first start on a cold CI disk is slow (macOS scans the bundle)
RUN_TIMEOUT = 180
ENGINES = {"pandas", "duckdb", "polars", "sql", "ibis", "curvefit_fit", "curvefit_eval"}

GEN = """import numpy as np
from scipy import stats
rng = np.random.default_rng(0)
df = pd.DataFrame({"g": rng.choice(["a", "b", "c"], 300), "x": stats.norm.rvs(size=300, random_state=1)})
"""


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", flush=True)
    raise SystemExit(1)


def main(exe: str) -> None:
    data = Path(tempfile.mkdtemp(prefix="sfs-smoke-"))
    t0 = time.monotonic()
    proc = subprocess.Popen([exe, "--data-dir", str(data)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr: list[str] = []
    threading.Thread(target=lambda: stderr.extend(proc.stderr), daemon=True).start()

    # ── readiness handshake ──
    port = None
    lines: list[str] = []
    def read_ready():
        nonlocal port
        for line in proc.stdout:
            if line.startswith("SFS_READY port="):
                port = int(line.split("port=")[1])
                return
            lines.append(line)
    reader = threading.Thread(target=read_ready, daemon=True)
    reader.start()
    reader.join(READY_TIMEOUT)
    if port is None:
        proc.kill()
        fail(f"no ready line after {time.monotonic() - t0:.0f}s\nstdout:\n{''.join(lines)}\n"
             f"stderr:\n{''.join(stderr[-60:])}")
    print(f"ready on port {port} in {time.monotonic() - t0:.1f}s", flush=True)
    base = f"http://127.0.0.1:{port}"

    def call(path: str, body: dict | None = None, method: str | None = None):
        req = urllib.request.Request(base + path, method=method or ("GET" if body is None else "POST"),
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode()
        except urllib.error.HTTPError as e:
            fail(f"{req.method} {path} -> {e.code}: {e.read().decode()[:500]}")

    try:
        # ── the app and its capabilities ──
        if 'id="root"' not in call("/"):
            fail("/ does not serve the frontend")
        caps = call("/api/capabilities/")
        available = {e["name"] for e in caps["engines"] if e["available"]}
        if ENGINES - available:
            fail(f"engines missing or unavailable: {sorted(ENGINES - available)}")
        if not caps["features"].get("desktop") or caps["features"].get("reports"):
            fail(f"unexpected features: {caps['features']}")
        print("capabilities ok:", sorted(available), flush=True)

        # ── a flow through every engine ──
        call("/api/connections/", {"name": "lite", "dialect": "sqlite", "database": str(data / "smoke.sqlite")})
        proj = call("/api/projects/", {"name": "Smoke test"})
        pid, flow = proj["id"], proj["flows"][0]
        trig = flow["nodes"][0]["id"]
        node = lambda i, d: {"id": i, "type": "processor", "position": {"x": 0, "y": 0}, "data": {"label": i, **d}}
        edge = lambda s, t: {"id": f"{s}-{t}", "source": s, "target": t, "sourceHandle": "out", "targetHandle": "in"}
        flow["nodes"] += [
            node("gen", {"engine": "pandas", "code": GEN}),
            node("duck", {"engine": "duckdb", "code": "SELECT g, COUNT(*) AS n, AVG(x) AS mean FROM df GROUP BY g ORDER BY g"}),
            node("pol", {"engine": "polars", "code": 'df = df.with_columns((pl.col("n") * 2).alias("n2"))'}),
            node("sql", {"engine": "sql", "target_connection": "lite", "code": "SELECT 41 + 1 AS answer"}),
        ]
        flow["edges"] += [edge(trig, "gen"), edge("gen", "duck"), edge("duck", "pol"), edge(trig, "sql")]
        call(f"/api/projects/{pid}", {"flows": [flow]}, method="PUT")
        call("/api/execute/run", {"project_id": pid, "flow_id": flow["id"], "flow_state": flow})

        deadline = time.monotonic() + RUN_TIMEOUT
        while time.monotonic() < deadline:
            runs = call(f"/api/runs/?project_id={pid}")
            if runs and runs[0]["status"] != "running":
                break
            time.sleep(0.5)
        else:
            fail("flow did not finish")
        if runs[0]["status"] != "ok":
            fail(f"flow {runs[0]['status']}: {runs[0].get('error')}")
        pol = call(f"/api/execute/frame/{pid}/pol")
        if pol["total"] != 3 or "n2" not in {c["name"] for c in pol["schema"]}:
            fail(f"unexpected Polars output: {pol['schema']}, {pol['total']} rows")
        if call(f"/api/execute/frame/{pid}/sql")["rows"] != [{"answer": 42}]:
            fail("SQL engine result is wrong")
        print(f"flow ok in {runs[0]['duration_ms']} ms (pandas, DuckDB, Polars, SQL)", flush=True)

        # ── Explore: chart query compiled by the WASM module ──
        q = {"workflow": [{"type": "view", "query": [{"op": "aggregate", "groupBy": ["g"], "measures": [
            {"field": "x", "agg": "sum", "asFieldKey": "s"}]}]}]}
        r = call("/api/explore/query", {"source": {"kind": "frame", "project_id": pid, "node_id": "gen"}, "payload": q})
        if len(r["rows"]) != 3:
            fail(f"Explore query returned {r['rows']}")
        print("explore ok", flush=True)
    except SystemExit:
        proc.kill()
        print("backend stderr (tail):\n" + "".join(stderr[-40:]), flush=True)
        raise

    # ── shutdown when the shell goes away ──
    proc.stdin.close()
    try:
        code = proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()
        fail("backend did not exit after stdin closed")
    if code != 0:
        fail(f"backend exited with {code}")
    print(f"PASS in {time.monotonic() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
