"""Core configuration and constants.

Uses environment variables for secrets and configuration. Follows PEP8 and Google style docstrings.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
import os

from pydantic import BaseModel


class Settings(BaseModel):
    """Application settings loaded from environment variables.

    Attributes:
        app_name: App display name.
        environment: Runtime environment.
        api_host: Host for FastAPI server.
        api_port: Port for FastAPI server.
        fitbit_client_id: OAuth2 Client ID for Fitbit.
        fitbit_client_secret: OAuth2 Client Secret for Fitbit.
        fitbit_redirect_uri: OAuth2 Redirect URI configured in Fitbit Developer.
        use_vosk_offline: Whether to use Vosk (offline) speech recognition.
        log_level: Logging level string.
    """

    app_name: str = "AI Fitness Smart Mirror"
    environment: Literal["dev", "prod", "test"] = "dev"

    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    fitbit_client_id: str | None = os.getenv("FITBIT_CLIENT_ID")
    fitbit_client_secret: str | None = os.getenv("FITBIT_CLIENT_SECRET")
    fitbit_redirect_uri: str | None = os.getenv("FITBIT_REDIRECT_URI")

    use_vosk_offline: bool = os.getenv("USE_VOSK_OFFLINE", "1") == "1"
    vosk_model_path: str | None = os.getenv("VOSK_MODEL_PATH")
    voice_intent_model_path: str | None = os.getenv("VOICE_INTENT_MODEL_PATH")
    voice_listener_enabled: bool = os.getenv("VOICE_LISTENER_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    voice_listener_device: int | None = (
        int(os.getenv("VOICE_LISTENER_DEVICE")) if (os.getenv("VOICE_LISTENER_DEVICE") or "").strip() else None
    )
    voice_listener_rate: int = int(os.getenv("VOICE_LISTENER_RATE", "16000"))
    voice_listener_blocksize: int = int(os.getenv("VOICE_LISTENER_BLOCKSIZE", "8000"))
    voice_listener_silence_window: float = float(os.getenv("VOICE_LISTENER_SILENCE_WINDOW", "1.0"))
    voice_listener_dedupe_seconds: float = float(os.getenv("VOICE_LISTENER_DEDUPE_SECONDS", "2.0"))
    voice_listener_base_url: str = os.getenv("VOICE_LISTENER_BASE_URL", "http://127.0.0.1:8000")

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Security & CORS
    api_key: str | None = os.getenv("API_KEY")
    exposed_origins: list[str] = (
        os.getenv("EXPOSED_ORIGINS", "*").split(",") if os.getenv("EXPOSED_ORIGINS") else ["*"]
    )

    # Biometrics / scheduling
    fitbit_poll_interval: int = int(os.getenv("FITBIT_POLL_INTERVAL", "15"))
    timezone: str = os.getenv("TIMEZONE", "America/Costa_Rica")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
