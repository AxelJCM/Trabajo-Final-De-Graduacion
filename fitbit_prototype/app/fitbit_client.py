from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

from .config import get_settings
from .token_store import load_tokens, save_tokens, Tokens


@dataclass
class Metrics:
    heart_rate_bpm: int
    steps: int


class FitbitClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.tokens: Optional[Tokens] = load_tokens()

    def _access_token(self) -> Optional[str]:
        return self.tokens.access_token if self.tokens else None

    async def _refresh_if_needed(self) -> None:
        if self.tokens is None:
            return
        if datetime.now(timezone.utc) < self.tokens.expires_at_utc:
            return
        await self.refresh()

    async def refresh(self) -> None:
        if httpx is None or self.tokens is None:
            return
        s = self.settings
        cid = (s.fitbit_client_id or "").strip().strip('"').strip("'")
        csec = (s.fitbit_client_secret or "").strip().strip('"').strip("'")
        url = "https://api.fitbit.com/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens.refresh_token,
            "client_id": cid,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        auth = httpx.BasicAuth(cid, csec) if csec else None
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, data=data, headers=headers, auth=auth)
            if r.status_code != 200:
                logger.warning("refresh failed: {} {}", r.status_code, r.text[:200])
                return
            body = r.json()
            self.tokens = save_tokens(
                body.get("access_token"),
                body.get("refresh_token", self.tokens.refresh_token),
                int(body.get("expires_in", 3600)),
                scope=body.get("scope"),
                token_type=body.get("token_type"),
            )

    async def get_metrics(self) -> Metrics:
        # fallback when no tokens
        if httpx is None or self.tokens is None:
            return Metrics(heart_rate_bpm=72, steps=0)
        await self._refresh_if_needed()
        token = self._access_token()
        if not token:
            return Metrics(heart_rate_bpm=72, steps=0)
        headers = {"Authorization": f"Bearer {token}"}
        date = datetime.now().astimezone().strftime("%Y-%m-%d")
        base = f"https://api.fitbit.com/1/user/-/activities/heart/date/{date}/1d/1sec.json"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(base, headers=headers)
            if r.status_code == 401:
                await self.refresh()
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                r = await client.get(base, headers=headers)
            if r.status_code >= 400:
                logger.warning("hr fetch failed: {} {}", r.status_code, r.text[:200])
                return Metrics(heart_rate_bpm=72, steps=0)
            body = r.json()
            series = None
            if isinstance(body, dict):
                intraday = body.get("activities-heart-intraday")
                if isinstance(intraday, dict):
                    series = intraday.get("dataset")
            hr = 72
            if isinstance(series, list) and series:
                last = series[-1]
                try:
                    hr = int(last.get("value", 72))
                except Exception:
                    hr = 72
            # steps
            steps_url = "https://api.fitbit.com/1/user/-/activities/steps/date/today/1d.json"
            r2 = await client.get(steps_url, headers=headers)
            steps = 0
            if r2.status_code == 200:
                b2 = r2.json()
                arr = b2.get("activities-steps") if isinstance(b2, dict) else None
                if isinstance(arr, list) and arr:
                    try:
                        steps = int(arr[-1].get("value", 0))
                    except Exception:
                        steps = 0
            return Metrics(heart_rate_bpm=hr, steps=steps)
