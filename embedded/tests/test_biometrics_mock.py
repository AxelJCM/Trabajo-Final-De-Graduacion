from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_biometrics_returns_mock_without_tokens():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/biometrics", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["heart_rate_bpm"] >= 0
    assert data["steps"] >= 0
    assert data["heart_rate_source"] in {"mock", "cached", "summary", "intraday"}
    assert data["fitbit_status_level"] in {"green", "yellow", "red"}
    assert "timestamp_utc" in data
    assert "zone_color" in data
