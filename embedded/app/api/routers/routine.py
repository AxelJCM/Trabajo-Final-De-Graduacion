"""Routine endpoint router for virtual trainer.

Generates and adapts workout routines as JSON blocks.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from loguru import logger

from app.api.schemas import Envelope, RoutineInput, RoutineOutput
from app.trainer.engine import TrainerEngine

router = APIRouter()

engine = TrainerEngine()


@router.post("/routine", response_model=Envelope)
async def routine_endpoint(payload: RoutineInput, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> Envelope:
    """Return an adapted routine for the user."""
    # Optional API key guard
    from app.core.config import get_settings
    s = get_settings()
    if s.api_key and x_api_key != s.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    routine: RoutineOutput = engine.generate_routine(payload.user_id, payload.performance)
    logger.info("routine={} blocks={} min={}", routine.routine_id, len(routine.blocks), routine.duration_min)
    return Envelope(success=True, data=routine.model_dump())
