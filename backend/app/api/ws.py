"""WebSocket endpoint — clients subscribe to a flow's execution events."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.ws_manager import ws_manager

router = APIRouter()


@router.websocket("/flow/{flow_id}")
async def flow_ws(flow_id: str, websocket: WebSocket):
    await ws_manager.connect(flow_id, websocket)
    try:
        while True:
            # Keep connection alive; client can send "ping"
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(flow_id, websocket)
