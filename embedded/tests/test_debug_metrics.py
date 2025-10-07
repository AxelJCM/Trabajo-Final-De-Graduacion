from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_debug_metrics_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/debug/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "latency_ms" in body and "fps" in body and "samples" in body
    assert "p50" in body["latency_ms"] and "p95" in body["latency_ms"]