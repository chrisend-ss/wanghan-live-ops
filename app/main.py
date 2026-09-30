from typing import List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect

from .auth import require_api_key
from .models import LiveEvent, StatsResponse
from .state import state

load_dotenv()

app = FastAPI(
    title="WangHan Live Ops Hub",
    version="0.1.0",
    description="Realtime event hub for WangHan live operations.",
)


@app.get("/health")
async def health():
    return {"ok": True, "service": "wanghan-live-ops"}


@app.post("/ingest")
async def ingest(event: LiveEvent, _: None = Depends(require_api_key)):
    await state.add_event(event)
    await state.broadcast(event)
    return {"ok": True}


@app.get("/events/recent", response_model=List[LiveEvent])
async def recent_events(
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(require_api_key),
):
    events = list(state.events)
    return events[-limit:]


@app.get("/stats", response_model=StatsResponse)
async def stats(_: None = Depends(require_api_key)):
    return state.stats()


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    state.clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state.clients.discard(websocket)
    except Exception:
        state.clients.discard(websocket)
        await websocket.close()
