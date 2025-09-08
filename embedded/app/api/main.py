"""FastAPI application exposing REST endpoints for the smart mirror.

Endpoints:
- POST /posture: posture analysis results (JSON)
- POST /biometrics: biometrics ingestion and retrieval (JSON)
- POST /routine: get or update current routine (JSON)
- POST /config: update/read configuration (JSON)

This module wires sub-routers from domain modules and provides a health check.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.routers.posture import router as posture_router
from app.api.routers.biometrics import router as biometrics_router
from app.api.routers.routine import router as routine_router
from app.api.routers.config_router import router as config_router

settings = get_settings()

app = FastAPI(title=settings.app_name)

# CORS for mobile app dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Return API health status."""

    return {"status": "ok"}


# Routers
app.include_router(posture_router, prefix="", tags=["posture"])
app.include_router(biometrics_router, prefix="", tags=["biometrics"])
app.include_router(routine_router, prefix="", tags=["routine"])
app.include_router(config_router, prefix="", tags=["config"])
