"""
WebSocket manager.

The frontend connects to /ws/flow/{flow_id} and receives real-time
execution events as JSON messages:

  { "type": "node_start",    "node_id": "...", "ts": 1234 }
  { "type": "node_complete", "node_id": "...", "rows_in": N, "rows_out": M, "duration_ms": D }
  { "type": "node_error",    "node_id": "...", "detail": "..." }
  { "type": "node_stopped",  "node_id": "...", "rows": N }
  { "type": "flow_complete", "duration_ms": D }
  { "type": "chart_ready",   "node_id": "...", "chart_type": "plotly|png", "payload": "..." }
  { "type": "table_ready",   "node_id": "...", "schema": [...], "rows": [...], "total": N }
"""
import json
import asyncio
from fastapi import WebSocket
from typing import DefaultDict
from collections import defaultdict


class ConnectionManager:
    def __init__(self):
        # flow_id → set of active WebSocket connections
        self._sockets: DefaultDict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, flow_id: str, ws: WebSocket):
        await ws.accept()
        self._sockets[flow_id].add(ws)

    def disconnect(self, flow_id: str, ws: WebSocket):
        self._sockets[flow_id].discard(ws)

    async def broadcast(self, flow_id: str, message: dict):
        """Send message to all listeners of a flow. Drops stale connections."""
        dead = set()
        payload = json.dumps(message)
        for ws in list(self._sockets.get(flow_id, [])):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._sockets[flow_id].discard(ws)

    def emit_sync(self, flow_id: str, message: dict):
        """Thread-safe emit from synchronous executor code."""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(flow_id, message), loop)


ws_manager = ConnectionManager()
