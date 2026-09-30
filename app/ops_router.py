from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import require_api_key
from .ops_models import (
    DailyReviewRequest,
    ExperimentCreate,
    ExperimentResultRequest,
    ExperimentStartRequest,
    MarkerCreateRequest,
    SessionStartRequest,
)
from .sessions import get_active_session_id, set_active_session_id
from .storage import storage


router = APIRouter(tags=["operations"])


@router.get("/sessions/active")
async def active_session(_: None = Depends(require_api_key)):
    session_id = get_active_session_id()
    if not session_id:
        return {"active_session_id": None}
    return {
        "active_session_id": session_id,
        "session": storage.get_session(session_id),
    }


@router.post("/sessions/start")
async def start_session(
    payload: SessionStartRequest,
    _: None = Depends(require_api_key),
):
    session = storage.start_session(payload.room_id, payload.title)
    set_active_session_id(session["id"])
    return session


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    _: None = Depends(require_api_key),
):
    if not storage.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    result = storage.stop_session(session_id)
    if get_active_session_id() == session_id:
        set_active_session_id(None)
    return result


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    _: None = Depends(require_api_key),
):
    session = storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/markers")
async def add_marker(
    session_id: str,
    payload: MarkerCreateRequest,
    _: None = Depends(require_api_key),
):
    if not storage.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return storage.add_marker(
        session_id=session_id,
        label=payload.label,
        note=payload.note,
        timestamp=payload.timestamp,
    )


@router.post("/experiments")
async def create_experiment(
    payload: ExperimentCreate,
    _: None = Depends(require_api_key),
):
    return storage.create_experiment(payload.model_dump(mode="json"))


@router.get("/experiments")
async def list_experiments(
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(require_api_key),
):
    return storage.list_experiments(category=category, status=status, limit=limit)


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    _: None = Depends(require_api_key),
):
    experiment = storage.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


@router.post("/experiments/{experiment_id}/start")
async def start_experiment(
    experiment_id: str,
    payload: ExperimentStartRequest,
    _: None = Depends(require_api_key),
):
    if not storage.get_session(payload.session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return storage.start_experiment(experiment_id, payload.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")


@router.put("/experiments/{experiment_id}/result")
async def save_experiment_result(
    experiment_id: str,
    payload: ExperimentResultRequest,
    _: None = Depends(require_api_key),
):
    try:
        return storage.save_experiment_result(
            experiment_id,
            payload.model_dump(mode="json"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Experiment not found")


@router.put("/reviews/{session_id}")
async def save_daily_review(
    session_id: str,
    payload: DailyReviewRequest,
    _: None = Depends(require_api_key),
):
    if not storage.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return storage.save_daily_review(session_id, payload.model_dump(mode="json"))


@router.get("/reviews/{session_id}")
async def get_daily_review(
    session_id: str,
    _: None = Depends(require_api_key),
):
    review = storage.get_daily_review(session_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review
