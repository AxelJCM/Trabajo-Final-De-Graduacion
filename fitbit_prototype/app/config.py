from __future__ import annotations

import os
from functools import lru_cache
from pydantic import BaseModel


class Settings(BaseModel):
    fitbit_client_id: str | None = os.getenv("FITBIT_CLIENT_ID")
    fitbit_client_secret: str | None = os.getenv("FITBIT_CLIENT_SECRET")
    fitbit_redirect_uri: str | None = os.getenv("FITBIT_REDIRECT_URI", "http://localhost:8787/auth/fitbit/callback")
    port: int = int(os.getenv("PORT", "8787"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
