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
        self.expires_at_utc = self._normalize_expiry(expires_at_utc)
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
                self.expires_at_utc = self._normalize_expiry(getattr(t, "expires_at_utc", None))

    def get_cached_hr(self) -> Optional[int]:
        return self._last_sample[0] if self._last_sample else None

    def get_cached_steps(self) -> Optional[int]:
        return self._last_steps[0] if self._last_steps else None

    @staticmethod
    def _normalize_expiry(value: Optional[datetime]) -> Optional[datetime]:
        """Convert stored expiry timestamps to timezone-aware UTC values."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                # Accept ISO strings persisted by older builds
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            value = parsed
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _extract_hr(self, payload: object) -> Tuple[Optional[int], str]:
        """Extract the latest HR sample from Fitbit response.

        Returns (value, source) where source is 'intraday', 'summary', or 'none'.
        """
        if not isinstance(payload, dict):
            return None, "none"

        def _from_dataset(dataset: object) -> Optional[int]:
            if isinstance(dataset, list) and dataset:
                last = dataset[-1]
                if isinstance(last, dict):
                    try:
                        return int(last.get("value", 0))
                    except Exception:
                        return None
            return None

        intraday = payload.get("activities-heart-intraday")
        if isinstance(intraday, dict):
            hr_val = _from_dataset(intraday.get("dataset"))
            if hr_val:
                return hr_val, "intraday"

        activities = payload.get("activities-heart")
        # Some responses (older mocks) used dict w/ dataset
        if isinstance(activities, dict):
            hr_val = _from_dataset(activities.get("dataset"))
            if hr_val:
                return hr_val, "intraday"
        # Official summary: list with value.restingHeartRate
        if isinstance(activities, list) and activities:
            entry = activities[-1]
            if isinstance(entry, dict):
                value = entry.get("value")
                if isinstance(value, dict):
                    rhr = value.get("restingHeartRate")
                    if isinstance(rhr, (int, float)) and rhr > 0:
                        return int(rhr), "summary"
                    # Last resort: pick highest zone a user spent time in
                    zones = value.get("heartRateZones")
                    if isinstance(zones, list):
                        for zone in reversed(zones):
                            if not isinstance(zone, dict):
                                continue
                            minutes = zone.get("minutes")
                            bpm = zone.get("min")
                            if isinstance(minutes, (int, float)) and minutes > 0 and isinstance(bpm, (int, float)):
                                return int(bpm), "summary"
        return None, "none"

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
        now_utc = datetime.now(timezone.utc)
        if self.expires_at_utc and now_utc >= self.expires_at_utc:
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
                hr, source = self._extract_hr(body)
                if hr is None or hr <= 0:
                    cached = self.get_cached_hr()
                    if cached is not None:
                        hr = cached
                    else:
                        hr = 72
                elif source == "summary":
                    logger.warning(
                        "Fitbit intraday series unavailable; using resting heart rate summary. "
                        "Request intraday access in Fitbit Developer portal for live samples."
                    )
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
        # Sanitize env values
        cid = (self.settings.fitbit_client_id or "").strip().strip('"').strip("'")
        csec = (self.settings.fitbit_client_secret or "").strip().strip('"').strip("'")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": cid,
        }
        if csec:
            data["client_secret"] = csec
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                auth = None
                if csec:
                    # Prefer Basic auth as in confidential flow
                    auth = httpx.BasicAuth(cid, csec)
                r = await client.post(
                    url,
                    data=data,
                    headers=headers,
                    auth=auth,
                )
                if r.status_code == 200:
                    body = r.json()
                    self.access_token = body.get("access_token")
                    self.refresh_token = body.get("refresh_token", self.refresh_token)
                    expires_in = body.get("expires_in", 3600)
                    self.expires_at_utc = self._normalize_expiry(
                        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    )
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
