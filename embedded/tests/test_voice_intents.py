import pytest
from httpx import AsyncClient
from app.api.main import app


@pytest.mark.asyncio
async def test_voice_test_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "inicia rutina de yoga"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success", True) in (True, False)
        assert data.get("data", {}).get("intent") == "start_routine"


@pytest.mark.asyncio
async def test_voice_start_session_synonym():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "iniciar sesion"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("data", {}).get("intent") == "start"


@pytest.mark.asyncio
async def test_voice_stop_session_synonym():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/voice/test", json={"utterance": "detener sesion"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("data", {}).get("intent") == "stop"

