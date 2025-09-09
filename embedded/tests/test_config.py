from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_config_roundtrip():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r1 = await ac.get("/config")
        assert r1.status_code == 200
        before = r1.json()["data"]
        r2 = await ac.post("/config", json={"language": "es", "intensity": "high"})
        assert r2.status_code == 200
        r3 = await ac.get("/config")
        after = r3.json()["data"]
        assert after["intensity"] == "high"