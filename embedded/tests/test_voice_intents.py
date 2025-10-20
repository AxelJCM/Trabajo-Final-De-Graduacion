import pytest
from httpx import AsyncClient
from app.api.main import app


@pytest.mark.asyncio
async def test_voice_start_command():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "iniciar"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data.get("data", {}).get("intent") == "start"


@pytest.mark.asyncio
async def test_voice_stop_session_synonym():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "detener"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("data", {}).get("intent") == "stop"


@pytest.mark.asyncio
async def test_voice_pause_command():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "pausa"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data.get("data", {}).get("intent") == "pause"


@pytest.mark.asyncio
async def test_voice_next_command():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "siguiente"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert data.get("data", {}).get("intent") == "next"

