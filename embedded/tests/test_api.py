from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_posture():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/posture", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "data" in body


@pytest.mark.asyncio
async def test_biometrics():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/biometrics", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True


@pytest.mark.asyncio
async def test_routine():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/routine", json={"user_id": "u1"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True


@pytest.mark.asyncio
async def test_config():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/config", json={"key": "log_level", "value": "DEBUG"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True