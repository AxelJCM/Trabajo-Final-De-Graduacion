"""Biometrics endpoint router integrating with Fitbit API.

Provides latest heart rate and steps using the biometrics client.
"""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.api.schemas import Envelope
from app.biometrics.fitbit_client import FitbitClient

router = APIRouter()


@router.post("/biometrics", response_model=Envelope)
async def biometrics_endpoint() -> Envelope:
    """Return latest biometrics from Fitbit API."""
    client = FitbitClient()
    m = await client.get_latest_metrics()
    logger.info("hr_bpm={} steps={}", m.heart_rate_bpm, m.steps)
    return Envelope(success=True, data={"heart_rate_bpm": m.heart_rate_bpm, "steps": m.steps})


@router.get("/biometrics/last", response_model=Envelope)
async def biometrics_last() -> Envelope:
    client = FitbitClient()
    hr = client.get_cached_hr()
    if hr is None:
        m = await client.get_latest_metrics()
        hr = m.heart_rate_bpm
        steps = m.steps
    else:
        steps = 0
    return Envelope(success=True, data={"heart_rate_bpm": hr, "steps": steps})
