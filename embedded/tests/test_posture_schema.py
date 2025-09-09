from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_posture_returns_data_without_camera():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/posture", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    d = body["data"]
    assert "joints" in d and isinstance(d["joints"], list)