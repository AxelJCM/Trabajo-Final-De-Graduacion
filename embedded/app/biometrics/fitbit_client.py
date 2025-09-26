"""Fitbit Web API integration (async, mock-first).

- Loads tokens from SQLite via DAL
- Fetches intraday heart rate with refresh/backoff
- Caches last HR sample for quick reads and polling loop
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from loguru import logger

try:  # Optional dependency; fall back to mock if unavailable
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.dal import get_tokens as dal_get_tokens, save_tokens as dal_save_tokens


@dataclass
class Metrics:
    heart_rate_bpm: int
    steps: int


class FitbitClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_at_utc: Optional[datetime] = None,
    ) -> None:
        self.settings = get_settings()
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at_utc = expires_at_utc
        self._last_sample: Optional[Tuple[int, datetime]] = None  # (hr, ts)
        self._last_steps: Optional[Tuple[int, datetime]] = None   # (steps, ts)

        if not access_token:
            db = SessionLocal()
            try:
                t = dal_get_tokens(db)
            finally:
                db.close()
            if t:
                self.access_token = t.access_token
                self.refresh_token = t.refresh_token
                self.expires_at_utc = t.expires_at_utc

    def get_cached_hr(self) -> Optional[int]:
        return self._last_sample[0] if self._last_sample else None

    def get_cached_steps(self) -> Optional[int]:
        return self._last_steps[0] if self._last_steps else None

    def _update_cache(self, hr: int):
        self._last_sample = (hr, datetime.now(timezone.utc))

    def _update_steps_cache(self, steps: int):
        self._last_steps = (steps, datetime.now(timezone.utc))

    async def get_latest_metrics(self) -> Metrics:
        # Mock-first behavior for offline/dev or missing deps/tokens
        if not self.access_token or httpx is None:
            hr = self.get_cached_hr() or 72
            steps = self.get_cached_steps() or 0
            self._update_cache(hr)
            self._update_steps_cache(steps)
            return Metrics(heart_rate_bpm=hr, steps=steps)

        # Refresh if expired
        if self.expires_at_utc and datetime.now(timezone.utc) >= self.expires_at_utc:
            await self._refresh()

        # Intraday HR endpoint (prefer 1sec, fallback 1min)
        date = datetime.now().astimezone().strftime("%Y-%m-%d")
        base = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d"
        paths = ["1sec", "1min"]
        headers = {"Authorization": f"Bearer {self.access_token}"}

        async def fetch(path: str):
            url = f"{base}/{path}.json"
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.get(url, headers=headers)

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
                    # try 1min granularity
                    resp = await fetch(paths[1])
                    if resp.status_code >= 400:
                        raise RuntimeError(f"Fitbit error {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
                series = None
                # Typical: body["activities-heart-intraday"]["dataset"]
                if isinstance(body, dict):
                    intraday = body.get("activities-heart-intraday")
                    if isinstance(intraday, dict):
                        series = intraday.get("dataset")
                    if not series:
                        alt = body.get("activities-heart")
                        if isinstance(alt, dict):
                            series = alt.get("dataset")
                if not series:
                    raise RuntimeError("No intraday HR series found")
                last = series[-1] if series else None
                hr = int(last.get("value", 0)) if last else 0
                if hr <= 0:
                    hr = self.get_cached_hr() or 72
                self._update_cache(hr)
                # Fetch daily steps similar to tutorial example
                steps = await self._get_daily_steps(headers)
                self._update_steps_cache(steps)
                return Metrics(heart_rate_bpm=hr, steps=steps)
            except Exception as exc:
                logger.warning("Fitbit fetch attempt {} failed: {}", attempt + 1, exc)
                await asyncio.sleep(delay)
                delay *= 2

        # Fallback
        hr = self.get_cached_hr() or 73
        steps = self.get_cached_steps() or 0
        self._update_cache(hr)
        self._update_steps_cache(steps)
        return Metrics(heart_rate_bpm=hr, steps=steps)

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
                r = await client.post(
                    url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if r.status_code == 200:
                    body = r.json()
                    self.access_token = body.get("access_token")
                    self.refresh_token = body.get("refresh_token", self.refresh_token)
                    expires_in = body.get("expires_in", 3600)
                    self.expires_at_utc = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    if self.access_token and self.refresh_token and expires_in:
                        db = SessionLocal()
                        try:
                            dal_save_tokens(
                                db,
                                self.access_token,
                                self.refresh_token,
                                int(expires_in),
                                provider="fitbit",
                                scope=body.get("scope"),
                                token_type=body.get("token_type"),
                            )
                        finally:
                            db.close()
                else:
                    logger.warning("Fitbit refresh failed: {} {}", r.status_code, r.text[:200])
        except Exception as exc:
            logger.warning("Fitbit refresh exception: {}", exc)

    async def _get_daily_steps(self, headers: dict) -> int:
        """Fetch daily steps using Fitbit activities/steps endpoint.

        Mirrors the tutorial's example endpoint usage but leverages stored OAuth tokens.
        Returns 0 on error.
        """
        if httpx is None or not self.access_token:
            return 0
        url = "https://api.fitbit.com/1/user/-/activities/steps/date/today/1d.json"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 401:
                    await self._refresh()
                    new_headers = {"Authorization": f"Bearer {self.access_token}"}
                    r = await client.get(url, headers=new_headers)
                if r.status_code >= 400:
                    logger.warning("Steps fetch failed: {} {}", r.status_code, r.text[:200])
                    return 0
                body = r.json()
                # body["activities-steps"] -> list of {dateTime, value}
                arr = body.get("activities-steps") if isinstance(body, dict) else None
                if isinstance(arr, list) and arr:
                    try:
                        return int(arr[-1].get("value", 0))
                    except Exception:
                        return 0
                return 0
        except Exception as exc:
            logger.warning("Steps fetch exception: {}", exc)
            return 0

    async def polling_loop(self, stop_event: asyncio.Event):
        interval = int(self.settings.fitbit_poll_interval)
        try:
            while not stop_event.is_set():
                try:
                    await self.get_latest_metrics()
                except Exception as exc:
                    logger.warning("Polling error: {}", exc)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("Fitbit polling task cancelled")
            raise
