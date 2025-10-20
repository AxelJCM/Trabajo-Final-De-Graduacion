"""Fitbit Web API integration (async, mock-first).

- Loads tokens from SQLite via DAL
- Fetches intraday heart rate with refresh/backoff
- Caches last HR sample for quick reads and polling loop
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
from collections import deque

from loguru import logger

try:  # Optional dependency; fall back to mock if unavailable
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.dal import (
    get_tokens as dal_get_tokens,
    save_tokens as dal_save_tokens,
    add_biometric_sample,
    get_last_biometric_sample,
)


@dataclass
class Metrics:
    """Container for Fitbit metrics along with provenance metadata."""

    heart_rate_bpm: int
    steps: int
    timestamp_utc: datetime
    heart_rate_source: str
    steps_source: str
    error: Optional[str] = None
    zone_name: Optional[str] = None
    zone_label: Optional[str] = None
    zone_color: Optional[str] = None
    intensity: float = 0.0
    fitbit_status: str = "unknown"
    fitbit_status_level: str = "yellow"
    fitbit_status_icon: str = "[?]"
    fitbit_status_message: Optional[str] = None
    staleness_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp_utc"] = self.timestamp_utc.isoformat()
        return d


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
        self._last_metrics: Optional[Metrics] = None
        self._last_error: Optional[str] = None
        self._history: deque[Metrics] = deque(maxlen=512)

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
        return self._last_metrics.heart_rate_bpm if self._last_metrics else None

    def get_cached_steps(self) -> Optional[int]:
        return self._last_metrics.steps if self._last_metrics else None

    def get_cached_metrics(self) -> Optional[Metrics]:
        if self._last_metrics:
            return self._decorate_metrics(self._last_metrics)
        db = SessionLocal()
        try:
            row = get_last_biometric_sample(db)
        finally:
            db.close()
        if not row:
            return None
        ts = row.timestamp_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        metrics = Metrics(
            heart_rate_bpm=row.heart_rate_bpm,
            steps=row.steps,
            timestamp_utc=ts,
            heart_rate_source=row.heart_rate_source or "cached",
            steps_source=row.steps_source or "cached",
            zone_name=row.zone_name,
            zone_label=row.zone_label,
            zone_color=row.zone_color,
            intensity=row.intensity or 0.0,
            fitbit_status=row.status or "cached",
            fitbit_status_icon=getattr(row, "status_icon", None) or "[?]",
            fitbit_status_message=row.status_message,
            error=None,
        )
        self._last_metrics = metrics
        self._history.append(metrics)
        return self._decorate_metrics(metrics)

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

    def _update_cache(
        self,
        *,
        heart_rate_bpm: int,
        steps: int,
        heart_rate_source: str,
        steps_source: str,
        error: Optional[str],
    ) -> Metrics:
        timestamp = datetime.now(timezone.utc)
        metrics = Metrics(
            heart_rate_bpm=heart_rate_bpm,
            steps=steps,
            timestamp_utc=timestamp,
            heart_rate_source=heart_rate_source,
            steps_source=steps_source,
            error=error,
        )
        metrics = self._decorate_metrics(metrics)
        self._last_metrics = metrics
        self._last_error = error
        self._history.append(metrics)
        self._persist_metrics(metrics)
        return metrics

    def _decorate_metrics(self, metrics: Metrics) -> Metrics:
        zone = self._compute_zone(metrics.heart_rate_bpm)
        metrics.zone_name = zone["name"]
        metrics.zone_label = zone["label"]
        metrics.zone_color = zone["color"]
        metrics.intensity = zone["intensity"]

        now = datetime.now(timezone.utc)
        staleness = max(0.0, (now - metrics.timestamp_utc).total_seconds())
        metrics.staleness_sec = staleness

        status = self._compute_status(metrics, staleness)
        metrics.fitbit_status = status["status"]
        metrics.fitbit_status_level = status["level"]
        metrics.fitbit_status_icon = status["icon"]
        metrics.fitbit_status_message = status["message"]
        return metrics

    def _compute_zone(self, hr: int) -> dict[str, Any]:
        rest = max(40, int(self.settings.hr_resting or 60))
        max_hr = max(rest + 10, int(self.settings.hr_max or 180))
        hrr = max(1, max_hr - rest)
        intensity = max(0.0, (hr - rest) / hrr)
        zones = [
            (0.45, ("below", "Reposo activo", "#5DADE2")),
            (0.6, ("warmup", "Calentamiento", "#48C9B0")),
            (0.75, ("fat_burn", "Zona quema grasa", "#52BE80")),
            (0.9, ("cardio", "Cardio", "#F39C12")),
            (1.2, ("peak", "Zona pico", "#E74C3C")),
        ]
        selected = ("rest", "Reposo", "#95A5A6")
        for threshold, zone in zones:
            if intensity < threshold:
                selected = zone
                break
        else:
            selected = zones[-1][1]
        return {
            "name": selected[0],
            "label": selected[1],
            "color": selected[2],
            "intensity": min(1.0, intensity),
        }

    def _compute_status(self, metrics: Metrics, staleness: float) -> dict[str, str]:
        icon_map = {"green": "[OK]", "yellow": "[!]", "red": "[X]"}
        interval = max(5, int(self.settings.fitbit_poll_interval or 15))
        if metrics.error:
            return {
                "status": "error",
                "level": "red",
                "icon": icon_map["red"],
                "message": f"Error Fitbit ({metrics.error})",
            }

        if staleness <= interval * 2:
            level = "green"
        elif staleness <= interval * 5:
            level = "yellow"
        else:
            level = "red"

        if metrics.heart_rate_source in {"mock", "cached"} and level == "green":
            level = "yellow"

        message = f"Última sync hace {int(staleness)}s"
        status = "ok" if level == "green" else ("stale" if level == "yellow" else "offline")
        return {
            "status": status,
            "level": level,
            "icon": icon_map.get(level, "[?]"),
            "message": message,
        }

    def _persist_metrics(self, metrics: Metrics) -> None:
        db = SessionLocal()
        try:
            add_biometric_sample(
                db,
                timestamp_utc=metrics.timestamp_utc.replace(tzinfo=None),
                heart_rate_bpm=metrics.heart_rate_bpm,
                steps=metrics.steps,
                heart_rate_source=metrics.heart_rate_source,
                steps_source=metrics.steps_source,
                zone_name=metrics.zone_name,
                zone_label=metrics.zone_label,
                zone_color=metrics.zone_color,
                intensity=float(metrics.intensity),
                status=metrics.fitbit_status,
                status_level=metrics.fitbit_status_level,
                status_icon=metrics.fitbit_status_icon,
                status_message=metrics.fitbit_status_message,
            )
        except Exception as exc:  # pragma: no cover - best effort persistence
            logger.warning("Failed to persist biometric sample: {}", exc)
        finally:
            db.close()

    def get_diagnostics(self) -> dict[str, Any]:
        """Return latest diagnostics for debug endpoints."""
        last = self._last_metrics
        return {
            "last_fetch_timestamp": last.timestamp_utc.isoformat() if last else None,
            "heart_rate_source": last.heart_rate_source if last else None,
            "steps_source": last.steps_source if last else None,
            "last_error": self._last_error,
            "tokens_loaded": bool(self.access_token),
            "poll_interval": int(self.settings.fitbit_poll_interval),
            "history_samples": len(self._history),
        }

    def get_metrics_since(self, since: datetime) -> list[Metrics]:
        """Return cached metrics captured since the provided timestamp."""
        if not self._history:
            return []
        since_utc = since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc)
        return [m for m in self._history if m.timestamp_utc >= since_utc]

    async def get_latest_metrics(self) -> Metrics:
        # Mock-first behavior for offline/dev or missing deps/tokens
        if not self.access_token or httpx is None:
            hr = self.get_cached_hr() or 72
            steps = self.get_cached_steps() or 0
            return self._update_cache(
                heart_rate_bpm=hr,
                steps=steps,
                heart_rate_source="mock" if httpx is None else "cached",
                steps_source="mock" if httpx is None else "cached",
                error="httpx_not_available" if httpx is None else None,
            )

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
                        metrics = self._last_metrics
                        return self._update_cache(
                            heart_rate_bpm=cached,
                            steps=metrics.steps if metrics else 0,
                            heart_rate_source=metrics.heart_rate_source if metrics else "cached",
                            steps_source=metrics.steps_source if metrics else "cached",
                            error="hr_missing_intraday",
                        )
                    hr = 72
                    source = "mock"
                elif source == "summary":
                    logger.warning(
                        "Fitbit intraday series unavailable; using resting heart rate summary. "
                        "Request intraday access in Fitbit Developer portal for live samples."
                    )
                # Fetch daily steps similar to tutorial example
                steps, steps_source = await self._get_daily_steps(headers)
                self._last_error = None
                return self._update_cache(
                    heart_rate_bpm=hr,
                    steps=steps,
                    heart_rate_source=source,
                    steps_source=steps_source,
                    error=None,
                )
            except Exception as exc:
                logger.warning("Fitbit fetch attempt {} failed: {}", attempt + 1, exc)
                self._last_error = str(exc)
                await asyncio.sleep(delay)
                delay *= 2

        # Fallback
        hr = self.get_cached_hr() or 73
        last = self._last_metrics
        steps = last.steps if last else 0
        return self._update_cache(
            heart_rate_bpm=hr,
            steps=steps,
            heart_rate_source=last.heart_rate_source if last else "cached",
            steps_source=last.steps_source if last else "cached",
            error=self._last_error or "fitbit_fetch_failed",
        )

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

    async def _get_daily_steps(self, headers: dict) -> Tuple[int, str]:
        """Fetch daily steps using Fitbit activities/steps endpoint.

        Mirrors the tutorial's example endpoint usage but leverages stored OAuth tokens.
        Returns (steps, source) tuple.
        """
        if httpx is None or not self.access_token:
            return 0, "mock"
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
                    return self.get_cached_steps() or 0, "cached"
                body = r.json()
                # body["activities-steps"] -> list of {dateTime, value}
                arr = body.get("activities-steps") if isinstance(body, dict) else None
                if isinstance(arr, list) and arr:
                    try:
                        return int(arr[-1].get("value", 0)), "daily"
                    except Exception:
                        return self.get_cached_steps() or 0, "cached"
                return self.get_cached_steps() or 0, "cached"
        except Exception as exc:
            logger.warning("Steps fetch exception: {}", exc)
            self._last_error = str(exc)
            return self.get_cached_steps() or 0, "cached"

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
