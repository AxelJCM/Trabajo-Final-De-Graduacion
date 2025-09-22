"""Session control endpoints.

Allows starting/stopping a workout session and selecting the active exercise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dal import add_session_metrics
from app.api.schemas import Envelope
from app.api.routers.posture import pose_estimator


router = APIRouter()

# Minimal in-memory session state
_state: Dict[str, Any] = {
    "started_at": None,  # datetime|None
    "rep_start": 0,
}


@router.post("/session/start", response_model=Envelope)
def session_start(payload: Optional[dict] = None) -> Envelope:
    ex = (payload or {}).get("exercise") if isinstance(payload, dict) else None
    if ex:
        pose_estimator.exercise = str(ex).lower()
        pose_estimator.phase = "up"
        pose_estimator.rep_count = 0
    _state["started_at"] = datetime.now(timezone.utc)
    _state["rep_start"] = pose_estimator.rep_count
    logger.info("Session started exercise={} rep_base={}", pose_estimator.exercise, _state["rep_start"])
    return Envelope(success=True, data={
        "exercise": pose_estimator.exercise,
        "started_at": _state["started_at"].isoformat(),
    })


@router.post("/session/stop", response_model=Envelope)
def session_stop(db: Session = Depends(get_db)) -> Envelope:
    if not _state.get("started_at"):
        return Envelope(success=False, error="no_active_session")
    started = _state["started_at"]
    duration = int((datetime.now(timezone.utc) - started).total_seconds())
    reps = max(0, pose_estimator.rep_count - int(_state.get("rep_start", 0)))
    # Persist minimal session metrics (avg_hr/max_hr/avg_quality left as 0 for now)
    try:
        add_session_metrics(db, started_at_utc=started.replace(tzinfo=None), duration_sec=duration, avg_hr=0, max_hr=0, avg_quality=0.0)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to persist session metrics: {}", exc)
    _state["started_at"] = None
    _state["rep_start"] = 0
    return Envelope(success=True, data={
        "duration_sec": duration,
        "reps": reps,
    })


@router.post("/session/exercise", response_model=Envelope)
def set_exercise(payload: dict) -> Envelope:
    ex = (payload or {}).get("exercise")
    if not ex:
        return Envelope(success=False, error="missing_exercise")
    pose_estimator.exercise = str(ex).lower()
    pose_estimator.phase = "up"
    pose_estimator.rep_count = 0
    _state["rep_start"] = 0
    logger.info("Exercise set to {} and counters reset", pose_estimator.exercise)
    return Envelope(success=True, data={"exercise": pose_estimator.exercise})


@router.get("/session/status", response_model=Envelope)
def session_status() -> Envelope:
    started = _state.get("started_at")
    duration = int((datetime.now(timezone.utc) - started).total_seconds()) if started else 0
    return Envelope(success=True, data={
        "exercise": pose_estimator.exercise,
        "phase": pose_estimator.phase,
        "rep_count": pose_estimator.rep_count,
        "started_at": started.isoformat() if started else None,
        "duration_sec": duration,
    })
