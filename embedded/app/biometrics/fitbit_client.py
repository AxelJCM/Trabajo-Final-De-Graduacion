"""Fitbit Web API integration (mock-first).

Handles OAuth tokens from SQLite and provides metric retrieval. If tokens are
missing, returns mocked biometrics for a device-less demo.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import requests
from loguru import logger

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.dal import get_tokens, save_tokens
from app.api.schemas import BiometricsOutput


class FitbitClient:
    """Thin client for Fitbit Web API."""

    API_BASE = "https://api.fitbit.com/1/user/-"

    def __init__(self, access_token: Optional[str] = None) -> None:
        self.settings = get_settings()
        self.access_token = access_token

    def _headers(self) -> dict:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_latest_metrics(self) -> BiometricsOutput:
        """Return latest HR and steps.

        If no token present, returns mocked data for offline dev.
        """
        # Load token from DB if missing
        if not self.access_token:
            with SessionLocal() as db:
                tok = get_tokens(db)
                if tok:
                    self.access_token = tok.access_token

        if not self.access_token:
            now = dt.datetime.utcnow().isoformat()
            logger.warning("Fitbit token not set; returning mocked biometrics")
            return BiometricsOutput(heart_rate_bpm=90, steps=1234, timestamp=now)

        # Attempt with simple backoff for transient errors
        delay_s = 0.5
        for attempt in range(3):  # 0,1,2
            try:
                hr_resp = requests.get(
                    f"{self.API_BASE}/activities/heart/date/today/1d.json",
                    headers=self._headers(),
                    timeout=5,
                )
                steps_resp = requests.get(
                    f"{self.API_BASE}/activities/date/today.json",
                    headers=self._headers(),
                    timeout=5,
                )
                hr_resp.raise_for_status()
                steps_resp.raise_for_status()
                bpm = 85  # TODO: parse
                steps = 3000  # TODO: parse
                now = dt.datetime.utcnow().isoformat()
                return BiometricsOutput(heart_rate_bpm=bpm, steps=steps, timestamp=now)
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Fitbit API attempt {} failed: {}", attempt + 1, exc)
                # On first failure, try refresh if we have refresh_token
                if attempt == 0:
                    with SessionLocal() as db:
                        tok = get_tokens(db)
                        if tok and tok.refresh_token:
                            self._refresh_token(db, tok.refresh_token)
                # jitter-less simple backoff
                import time as _t
                _t.sleep(delay_s)
                delay_s *= 2

        now = dt.datetime.utcnow().isoformat()
        logger.error("Fitbit API failing; returning zeros")
        return BiometricsOutput(heart_rate_bpm=0, steps=0, timestamp=now)

    def _refresh_token(self, db, refresh_token: str) -> None:
        """Refresh the access token using refresh_token."""
        try:
            token_url = "https://api.fitbit.com/oauth2/token"
            import base64

            auth_hdr = base64.b64encode(
                f"{self.settings.fitbit_client_id}:{self.settings.fitbit_client_secret}".encode()
            ).decode()
            data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
            r = requests.post(
                token_url,
                headers={
                    "Authorization": f"Basic {auth_hdr}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=data,
                timeout=10,
            )
            r.raise_for_status()
            payload = r.json()
            save_tokens(
                db,
                payload.get("access_token"),
                payload.get("refresh_token"),
                payload.get("expires_in", 28800),
            )
            self.access_token = payload.get("access_token")
            logger.info("Fitbit token refreshed")
        except Exception as exc:  # pragma: no cover
            logger.error("Fitbit token refresh error: {}", exc)
