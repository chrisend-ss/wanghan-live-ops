from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExperimentCategory(str, Enum):
    visual = "visual"
    opening = "opening"
    content = "content"
    audience = "audience"
    retention = "retention"
    clips = "clips"
    other = "other"


class ExperimentCreate(BaseModel):
    category: ExperimentCategory
    name: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    target_metric: str = Field(min_length=1)
    variables: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    control_experiment_id: Optional[str] = None
    notes: str = ""


class ExperimentStartRequest(BaseModel):
    session_id: str = Field(min_length=1)


class ExperimentResultRequest(BaseModel):
    metrics: Dict[str, Any] = Field(default_factory=dict)
    conclusion: str = ""
    decision: str = Field(
        default="inconclusive",
        description="keep / reject / iterate / inconclusive",
    )
    next_experiment: str = ""


class SessionStartRequest(BaseModel):
    room_id: str = Field(min_length=1)
    title: str = ""


class MarkerCreateRequest(BaseModel):
    label: str = Field(min_length=1)
    note: str = ""
    timestamp: Optional[str] = None


class DailyReviewRequest(BaseModel):
    entry_winners: List[Dict[str, Any]] = Field(default_factory=list)
    retention_winners: List[Dict[str, Any]] = Field(default_factory=list)
    interaction_revenue_winners: List[Dict[str, Any]] = Field(default_factory=list)
    waste_points: List[Dict[str, Any]] = Field(default_factory=list)
    clip_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    findings: List[str] = Field(default_factory=list)
    next_tests: List[str] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
