"""Session control endpoints.

Provides start/pause/stop controls, persistence, and history endpoints.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dal import (
    add_session_metrics,
    get_last_session_metrics,
    get_session_history,
)
from app.api.schemas import Envelope, SessionMetricsOutput
from app.api.routers.posture import pose_estimator

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mark_command(name: str) -> None:
    ts = _now()
    _state["last_command"] = name
    _state["last_command_ts"] = ts


def _register_voice_event(message: str, intent: Optional[str] = None) -> dict[str, Any]:
    now = _now()
    seq = int(_state.get("voice_event_seq") or 0) + 1
    payload = {
        "message": message,
        "intent": intent,
        "timestamp": now.isoformat(),
        "seq": seq,
    }
    _state["voice_event"] = payload
    _state["voice_event_seq"] = seq
    return payload


def _accumulate_active(now: Optional[datetime] = None) -> None:
    now = now or _now()
    active_started = _state.get("active_started_at")
    if _state.get("status") == "active" and isinstance(active_started, datetime):
        elapsed = (now - active_started).total_seconds()
        _state["accum_active"] = float(_state.get("accum_active", 0.0) or 0.0) + max(0.0, elapsed)
        _state["active_started_at"] = None


def _active_duration(now: Optional[datetime] = None) -> int:
    now = now or _now()
    accum = float(_state.get("accum_active", 0.0) or 0.0)
    active_started = _state.get("active_started_at")
    if _state.get("status") == "active" and isinstance(active_started, datetime):
        accum += max(0.0, (now - active_started).total_seconds())
    return max(0, int(accum))


_state: dict[str, Any] = {
    "started_at": None,
    "status": "idle",
    "active_started_at": None,
    "accum_active": 0.0,
    "exercise": pose_estimator.exercise,
    "last_command": None,
    "last_command_ts": None,
    "requires_start": True,
    "last_summary": None,
    "voice_event": None,
    "voice_event_seq": 0,
}


@router.post("/session/start", response_model=Envelope)
def session_start(payload: Optional[dict] = None) -> Envelope:
    data = payload or {}
    exercise = data.get("exercise")
    reset_totals = bool(data.get("reset", True))
    resume = bool(data.get("resume", False))

    if _state.get("started_at") and _state.get("status") == "paused" and (resume or not reset_totals):
        now = _now()
        _state["status"] = "active"
        _state["active_started_at"] = now
        _state["requires_start"] = False
        _state["last_summary"] = None
        pose_estimator.set_counting_enabled(True)
        _mark_command("resume")
        logger.info("Session resumed")
        return Envelope(
            success=True,
            data={
                "status": "active",
                "exercise": _state.get("exercise"),
                "started_at": (_state.get("started_at") or now).isoformat(),
            },
        )

    if exercise:
        pose_estimator.set_exercise(str(exercise), reset=True)
    else:
        pose_estimator.reset_session(
            preserve_totals=not reset_totals,
            exercise=pose_estimator.exercise,
        )

    now = _now()
    _state.update(
        {
            "started_at": now,
            "status": "active",
            "active_started_at": now,
            "accum_active": 0.0,
            "exercise": pose_estimator.exercise,
            "requires_start": False,
            "last_summary": None,
        }
    )
    pose_estimator.set_counting_enabled(True)
    _mark_command("start")
    logger.info("Session started exercise={} reset_totals={}", pose_estimator.exercise, reset_totals)
    return Envelope(
        success=True,
        data={
            "exercise": pose_estimator.exercise,
            "started_at": now.isoformat(),
            "status": "active",
        },
    )


@router.post("/session/pause", response_model=Envelope)
def session_pause() -> Envelope:
    if not isinstance(_state.get("started_at"), datetime):
        return Envelope(success=False, error="no_active_session")
    if _state.get("status") != "active":
        return Envelope(success=True, data={"status": _state.get("status")})
    now = _now()
    _accumulate_active(now)
    _state["status"] = "paused"
    pose_estimator.set_counting_enabled(False)
    _mark_command("pause")
    logger.info("Session paused")
    return Envelope(
        success=True,
        data={
            "status": "paused",
            "duration_active_sec": _active_duration(now),
        },
    )


@router.post("/session/stop", response_model=Envelope)
def session_stop(request: Request, db: Session = Depends(get_db)) -> Envelope:
    started = _state.get("started_at")
    if not isinstance(started, datetime):
        return Envelope(success=False, error="no_active_session")

    now = _now()
    _accumulate_active(now)
    duration_total = max(0, int((now - started).total_seconds()))
    duration_active = _active_duration(now)
    rep_breakdown = dict(pose_estimator.rep_totals)
    total_reps = sum(rep_breakdown.values())
    current_reps = pose_estimator.rep_count
    avg_quality = pose_estimator.get_average_quality()

    avg_hr = 0
    max_hr = 0
    fitbit_client = getattr(request.app.state, "fitbit_client", None)
    if fitbit_client and isinstance(started, datetime):
        try:
            samples = fitbit_client.get_metrics_since(started)
            if samples:
                values = [m.heart_rate_bpm for m in samples]
                avg_hr = int(sum(values) / len(values))
                max_hr = max(values)
        except Exception as exc:  # pragma: no cover - telemetry only
            logger.warning("Failed to compute HR stats for session_stop: {}", exc)

    try:
        add_session_metrics(
            db,
            started_at_utc=started.replace(tzinfo=None),
            ended_at_utc=now.replace(tzinfo=None),
            duration_sec=duration_total,
            duration_active_sec=duration_active,
            avg_hr=avg_hr,
            max_hr=max_hr,
            avg_quality=avg_quality,
            total_reps=total_reps,
            exercise=_state.get("exercise"),
        )
    except Exception as exc:  # pragma: no cover - persistence fallback
        logger.warning("Failed to persist session metrics: {}", exc)

    summary = {
        "duration_sec": duration_total,
        "duration_active_sec": duration_active,
        "total_reps": total_reps,
        "rep_breakdown": rep_breakdown,
        # Include quality average in the session summary for GUI consumption
        "avg_quality": avg_quality,
    }

    pose_estimator.reset_session(exercise=_state.get("exercise"), preserve_totals=False)
    pose_estimator.set_counting_enabled(False)
    _state.update(
        {
            "started_at": None,
            "status": "idle",
            "active_started_at": None,
            "accum_active": 0.0,
            "requires_start": True,
            "last_summary": summary,
        }
    )
    _mark_command("stop")
    logger.info("Session stopped duration={} reps={}", duration_total, total_reps)

    return Envelope(
        success=True,
        data={
            "duration_sec": duration_total,
            "duration_active_sec": duration_active,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "avg_quality": avg_quality,
            "rep_count": current_reps,
            "total_reps": total_reps,
            "rep_breakdown": rep_breakdown,
        },
    )


@router.post("/session/exercise", response_model=Envelope)
def set_exercise(payload: dict) -> Envelope:
    ex = (payload or {}).get("exercise")
    if not ex:
        return Envelope(success=False, error="missing_exercise")
    reset = bool((payload or {}).get("reset", False))
    pose_estimator.set_exercise(str(ex), reset=reset)
    _state["exercise"] = pose_estimator.exercise
    _mark_command("next")
    logger.info("Exercise changed to {} reset={}", pose_estimator.exercise, reset)
    return Envelope(success=True, data={"exercise": pose_estimator.exercise, "reset": reset})


@router.get("/session/status", response_model=Envelope)
def session_status() -> Envelope:
    started = _state.get("started_at")
    now = _now()
    duration = max(0, int((now - started).total_seconds())) if isinstance(started, datetime) else 0
    phase_label = pose_estimator.get_phase_label()
    return Envelope(
        success=True,
        data={
            "status": _state.get("status"),
            "exercise": pose_estimator.exercise,
            "phase": pose_estimator.phase,
            "phase_label": phase_label,
            "rep_count": pose_estimator.rep_count,
            "rep_totals": pose_estimator.rep_totals,
            "avg_quality": pose_estimator.get_average_quality(),
            "feedback": pose_estimator.feedback,
            "feedback_code": pose_estimator.feedback_code,
            "started_at": started.isoformat() if isinstance(started, datetime) else None,
            "duration_sec": duration,
            "duration_active_sec": _active_duration(now),
            "last_command": _state.get("last_command"),
            "last_command_ts": (
                _state["last_command_ts"].isoformat() if isinstance(_state.get("last_command_ts"), datetime) else None
            ),
            "requires_voice_start": bool(_state.get("requires_start")),
            "session_summary": _state.get("last_summary"),
            "voice_event": _state.get("voice_event"),
        },
    )


@router.post("/session/voice-event", response_model=Envelope)
def session_voice_event(payload: Optional[dict] = None) -> Envelope:
    data = payload or {}
    message = data.get("message")
    if not message:
        return Envelope(success=False, error="missing_message")
    intent = data.get("intent")
    event = _register_voice_event(str(message), intent=str(intent) if intent is not None else None)
    return Envelope(success=True, data=event)


@router.get("/session/last", response_model=Envelope)
def session_last(db: Session = Depends(get_db)) -> Envelope:
    row = get_last_session_metrics(db)
    if not row:
        return Envelope(success=True, data=None)
    payload = SessionMetricsOutput.model_validate(row)
    return Envelope(success=True, data=payload.model_dump(by_alias=True))


@router.get("/session/history", response_model=Envelope)
def session_history(
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100),
) -> Envelope:
    rows = get_session_history(db, limit=limit)
    items = [
        SessionMetricsOutput.model_validate(row).model_dump(by_alias=True)
        for row in rows
    ]
    return Envelope(success=True, data={"sessions": items, "count": len(items)})



