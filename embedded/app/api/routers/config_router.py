"""Config endpoint router for reading/writing runtime configuration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import Envelope, ConfigInput, ConfigOutput
from app.core.config import get_settings
from app.core.db import get_db, Base, engine
from app.core.models import UserConfig
from app.core.dal import get_user_config, save_user_config

router = APIRouter()

# Ensure tables exist at import time (idempotent)
Base.metadata.create_all(bind=engine)


@router.get("/config", response_model=Envelope)
async def get_config(db: Session = Depends(get_db)) -> Envelope:
    cfg = get_user_config(db)
    out = ConfigOutput(language=cfg.language, intensity=cfg.intensity, units=cfg.units, tz=cfg.tz)
    return Envelope(success=True, data=out.model_dump())


@router.post("/config", response_model=Envelope)
async def set_config(
    payload: ConfigInput,
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Envelope:
    s = get_settings()
    if getattr(s, "api_key", None) and x_api_key != s.api_key:
        raise HTTPException(status_code=401, detail="invalid_api_key")
    cfg = save_user_config(db, language=payload.language, intensity=payload.intensity, units=payload.units, tz=payload.tz)
    out = ConfigOutput(language=cfg.language, intensity=cfg.intensity, units=cfg.units, tz=cfg.tz)
    return Envelope(success=True, data=out.model_dump())
