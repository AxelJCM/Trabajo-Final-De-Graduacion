"""Biometrics endpoint router integrating with Fitbit API.

Provides latest heart rate and steps using the biometrics client.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from loguru import logger

from app.api.schemas import Envelope, BiometricsOutput
from app.biometrics.fitbit_client import FitbitClient

router = APIRouter()


@router.post("/biometrics", response_model=Envelope)
async def biometrics_endpoint(request: Request) -> Envelope:
    """Return latest biometrics from Fitbit API."""
    client = _ensure_client(request)
    m = await client.get_latest_metrics()
    logger.info(
        "biometrics fetch hr_bpm={} steps={} hr_source={} steps_source={}",
        m.heart_rate_bpm,
        m.steps,
        m.heart_rate_source,
        m.steps_source,
    )
    payload = BiometricsOutput.model_validate(m.to_dict())
    return Envelope(success=True, data=payload.model_dump())


@router.get("/biometrics/last", response_model=Envelope)
async def biometrics_last(request: Request) -> Envelope:
    client = _ensure_client(request)
    metrics = client.get_cached_metrics()
    if metrics is None:
        metrics = await client.get_latest_metrics()
    payload = BiometricsOutput.model_validate(metrics.to_dict())
    return Envelope(success=True, data=payload.model_dump())


def _ensure_client(request: Request) -> FitbitClient:
    client = getattr(request.app.state, "fitbit_client", None)
    if isinstance(client, FitbitClient):
        return client
    client = FitbitClient()
    request.app.state.fitbit_client = client
    return client
