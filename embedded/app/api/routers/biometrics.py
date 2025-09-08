"""Biometrics endpoint router integrating with Fitbit API.

Provides latest heart rate and steps using the biometrics client.
"""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.api.schemas import Envelope, BiometricsInput, BiometricsOutput
from app.biometrics.fitbit_client import FitbitClient

router = APIRouter()

client = FitbitClient()


@router.post("/biometrics", response_model=Envelope)
async def biometrics_endpoint(payload: BiometricsInput) -> Envelope:
    """Return latest biometrics from Fitbit API."""
    data: BiometricsOutput = client.get_latest_metrics()
    logger.info("hr_bpm={} steps={}", data.heart_rate_bpm, data.steps)
    return Envelope(success=True, data=data.model_dump())
