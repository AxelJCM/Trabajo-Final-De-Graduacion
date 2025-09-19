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
                from __future__ import annotations

                import asyncio
                import random
                from dataclasses import dataclass
                from datetime import datetime, timezone, timedelta
                from typing import Optional, Tuple

                from loguru import logger

                try:
                    import httpx
                except Exception:  # pragma: no cover
                    httpx = None  # type: ignore

                from app.core.dal import get_tokens, save_tokens
                from app.core.config import get_settings


                @dataclass
                class Metrics:
                    heart_rate_bpm: int
                    steps: int


                class FitbitClient:
                    def __init__(self, access_token: Optional[str] = None, refresh_token: Optional[str] = None, expires_at_utc: Optional[datetime] = None):
                        self.settings = get_settings()
                        self.access_token = access_token
                        self.refresh_token = refresh_token
                        self.expires_at_utc = expires_at_utc
                        self.tz = self.settings.timezone
                        self._last_sample: Optional[Tuple[int, datetime]] = None  # (hr, ts)
                        if not access_token:
                            t = get_tokens()
                            if t:
                                self.access_token = t.access_token
                                self.refresh_token = t.refresh_token
                                self.expires_at_utc = t.expires_at_utc

                    def get_cached_hr(self) -> Optional[int]:
                        return self._last_sample[0] if self._last_sample else None

                    def _update_cache(self, hr: int):
                        self._last_sample = (hr, datetime.now(timezone.utc))

                    async def get_latest_metrics(self) -> Metrics:
                        # Mock-first behavior
                        if not self.access_token or httpx is None:
                            hr = 72
                            self._update_cache(hr)
                            return Metrics(heart_rate_bpm=hr, steps=1000)

                        # Refresh if expired
                        if self.expires_at_utc and datetime.now(timezone.utc) >= self.expires_at_utc:
                            await self._refresh()

                        # Intraday HR endpoint (1s granularity preferred)
                        # Example: /1/user/-/activities/heart/date/today/1d/1sec/time/00:00/23:59.json
                        date = datetime.now().astimezone().strftime("%Y-%m-%d")
                        base = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d"
                        paths = ["1sec", "1min"]
                        headers = {"Authorization": f"Bearer {self.access_token}"}

                        async def fetch(path: str):
                            url = f"{base}/{path}.json"
                            async with httpx.AsyncClient(timeout=10) as client:
                                return await client.get(url, headers=headers)

                        # Retry with backoff, handle 401 -> refresh
                        delay = 0.5
                        for attempt in range(5):
                            try:
                                resp = await fetch(paths[0])
                                if resp.status_code == 401:
                                    await self._refresh()
                                    headers["Authorization"] = f"Bearer {self.access_token}"
                                    continue
                                if resp.status_code == 429:
                                    sleep_s = delay + random.uniform(0, delay)
                                    logger.warning("429 rate limit; backing off {:.2f}s", sleep_s)
                                    await asyncio.sleep(sleep_s)
                                    delay *= 2
                                    continue
                                if resp.status_code >= 400:
                                    # try 1min
                                    resp = await fetch(paths[1])
                                    if resp.status_code >= 400:
                                        raise RuntimeError(f"Fitbit error {resp.status_code}: {resp.text[:200]}")
                                body = resp.json()
                                series = None
                                for key in ("activities-heart-intraday", "activities-heart"):  # intraday in first
                                    if key in body and isinstance(body[key], dict) and "dataset" in body[key]:
                                        series = body[key]["dataset"]
                                        break
                                if not series:
                                    raise RuntimeError("No intraday HR series found")
                                last = series[-1] if series else None
                                hr = int(last.get("value", 0)) if last else 0
                                if hr <= 0:
                                    hr = self.get_cached_hr() or 72
                                self._update_cache(hr)
                                return Metrics(heart_rate_bpm=hr, steps=0)
                            except Exception as exc:
                                logger.warning("Fitbit fetch attempt {} failed: {}", attempt + 1, exc)
                                await asyncio.sleep(delay)
                                delay *= 2
                        # Fallback
                        hr = self.get_cached_hr() or 73
                        self._update_cache(hr)
                        return Metrics(heart_rate_bpm=hr, steps=0)

                    async def _refresh(self):
                        if httpx is None or not self.refresh_token:
                            return
                        url = "https://api.fitbit.com/oauth2/token"
                        data = {
                            "grant_type": "refresh_token",
                            "refresh_token": self.refresh_token,
                            "client_id": self.settings.fitbit_client_id,
                            "client_secret": self.settings.fitbit_client_secret,
                        }
                        try:
                            async with httpx.AsyncClient(timeout=10) as client:
                                r = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
                                if r.status_code == 200:
                                    body = r.json()
                                    self.access_token = body.get("access_token")
                                    self.refresh_token = body.get("refresh_token", self.refresh_token)
                                    expires_in = body.get("expires_in", 3600)
                                    self.expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                                    save_tokens(self.access_token, self.refresh_token, self.expires_at_utc)
                                else:
                                    logger.warning("Fitbit refresh failed: {} {}", r.status_code, r.text[:200])
                        except Exception as exc:
                            logger.warning("Fitbit refresh exception: {}", exc)

                    async def polling_loop(self, stop_event: asyncio.Event):
                        interval = int(self.settings.fitbit_poll_interval)
                        while not stop_event.is_set():
                            try:
                                await self.get_latest_metrics()
                            except Exception as exc:
                                logger.warning("Polling error: {}", exc)
                            await asyncio.sleep(interval)
