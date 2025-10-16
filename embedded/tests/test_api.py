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


# routine endpoint removed per scope reduction


@pytest.mark.asyncio
async def test_config():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/config", json={"key": "log_level", "value": "DEBUG"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True


@pytest.mark.asyncio
async def test_session_lifecycle():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/session/start", json={"exercise": "squat"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "active"

        status = await ac.get("/session/status")
        assert status.status_code == 200
        status_data = status.json()["data"]
        assert status_data["status"] == "active"

        pause = await ac.post("/session/pause", json={})
        assert pause.status_code == 200
        resume = await ac.post("/session/start", json={"resume": True, "reset": False})
        assert resume.status_code == 200

        stop = await ac.post("/session/stop", json={})
        assert stop.status_code == 200
        stop_data = stop.json()["data"]
        assert "total_reps" in stop_data

        last = await ac.get("/session/last")
        assert last.status_code == 200

        history = await ac.get("/session/history?limit=5")
        assert history.status_code == 200
        history_data = history.json()["data"]
        assert "sessions" in history_data
