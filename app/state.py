import asyncio
import os
from collections import Counter, deque
from typing import Deque, Dict, Optional, Set

from fastapi import WebSocket

from .models import LiveEvent


class LiveState:
    def __init__(self) -> None:
        limit = int(os.getenv("RECENT_EVENT_LIMIT", "2000"))
        self.events: Deque[LiveEvent] = deque(maxlen=limit)
        self.clients: Set[WebSocket] = set()
        self.counter: Counter[str] = Counter()
        self.latest_audience: Optional[int] = None
        self.latest_total_viewers: Optional[int] = None
        self.lock = asyncio.Lock()

    async def add_event(self, event: LiveEvent) -> None:
        async with self.lock:
            self.events.append(event)
            self.counter[event.type.value] += 1

            if event.type.value == "audience_stats":
                audience = event.metadata.get("current_audience")
                total = event.metadata.get("total_viewers")
                if isinstance(audience, int):
                    self.latest_audience = audience
                if isinstance(total, int):
                    self.latest_total_viewers = total

    async def broadcast(self, event: LiveEvent) -> None:
        dead = []
        payload = event.model_dump(mode="json")
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def stats(self) -> Dict:
        return {
            "total_events": sum(self.counter.values()),
            "by_type": dict(self.counter),
            "latest_audience": self.latest_audience,
            "latest_total_viewers": self.latest_total_viewers,
            "gifts": self.counter.get("gift", 0),
            "likes": self.counter.get("like", 0),
            "chats": self.counter.get("chat", 0),
            "enters": self.counter.get("enter", 0),
        }


state = LiveState()
