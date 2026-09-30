from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    chat = "chat"
    enter = "enter"
    like = "like"
    gift = "gift"
    fanclub = "fanclub"
    audience_stats = "audience_stats"
    follow = "follow"
    system = "system"


class LiveEvent(BaseModel):
    type: EventType
    room_id: str = Field(min_length=1)
    user_id: Optional[str] = None
    nickname: Optional[str] = None
    content: Optional[str] = None
    count: Optional[int] = None
    value: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    total_events: int
    by_type: Dict[str, int]
    latest_audience: Optional[int] = None
    latest_total_viewers: Optional[int] = None
    gifts: int = 0
    likes: int = 0
    chats: int = 0
    enters: int = 0
