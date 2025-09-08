"""Config endpoint router for reading/writing runtime configuration."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import Envelope, ConfigInput, ConfigOutput
from app.core.config import get_settings

router = APIRouter()

_config_store: dict[str, ConfigOutput] = {}


@router.post("/config", response_model=Envelope)
async def config_endpoint(payload: ConfigInput) -> Envelope:
    """Set or get a configuration value."""
    if payload.value is not None:
        _config_store[payload.key] = ConfigOutput(key=payload.key, value=payload.value)
    value = _config_store.get(payload.key, ConfigOutput(key=payload.key, value=getattr(get_settings(), payload.key, None)))
    return Envelope(success=True, data=value.model_dump())
