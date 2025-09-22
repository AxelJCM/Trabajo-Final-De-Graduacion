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
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.core.config import get_settings
from app.api.routers.posture import router as posture_router
from app.api.routers.biometrics import router as biometrics_router
from app.api.routers.routine import router as routine_router
from app.api.routers.config_router import router as config_router
from app.api.routers.auth import router as auth_router
from app.api.routers.voice import router as voice_router
from app.api.routers.session import router as session_router
from app.api.routers.debug import router as debug_router
from app.core.db import engine, Base, SessionLocal
from app.core.dal import get_tokens
import asyncio
from app.biometrics.fitbit_client import FitbitClient
from loguru import logger

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB tables exist
    Base.metadata.create_all(bind=engine)
    # Configure file logging
    logs_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(logs_dir / "app.log", rotation="5 MB", retention="7 days", enqueue=True, backtrace=False, diagnose=False)
    # Start Fitbit polling if tokens exist
    db = SessionLocal()
    stop_event = asyncio.Event()
    try:
        if get_tokens(db):
            client = FitbitClient()
            task = asyncio.create_task(client.polling_loop(stop_event))
            app.state._fitbit_task = task
            app.state._fitbit_stop = stop_event
    finally:
        db.close()
    yield
    # Shutdown: stop polling
    if getattr(app.state, "_fitbit_stop", None):
        app.state._fitbit_stop.set()
    if getattr(app.state, "_fitbit_task", None):
        await app.state._fitbit_task


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# CORS for mobile app dev
s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.exposed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
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
app.include_router(auth_router, prefix="", tags=["auth"])
app.include_router(voice_router, prefix="", tags=["voice"])
app.include_router(debug_router, prefix="", tags=["debug"])
app.include_router(session_router, prefix="", tags=["session"])
