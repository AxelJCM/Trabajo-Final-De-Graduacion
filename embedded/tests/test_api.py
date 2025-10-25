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
        assert status_data["requires_voice_start"] is False
        assert status_data["session_summary"] is None

        pause = await ac.post("/session/pause", json={})
        assert pause.status_code == 200
        resume = await ac.post("/session/start", json={"resume": True, "reset": False})
        assert resume.status_code == 200

        stop = await ac.post("/session/stop", json={})
        assert stop.status_code == 200
        stop_data = stop.json()["data"]
        assert "total_reps" in stop_data

        status_post_stop = await ac.get("/session/status")
        assert status_post_stop.status_code == 200
        status_after_stop = status_post_stop.json()["data"]
        assert status_after_stop["requires_voice_start"] is True
        summary = status_after_stop.get("session_summary")
        assert summary is not None
        assert isinstance(summary.get("rep_breakdown"), dict)

        restart = await ac.post("/session/start", json={"exercise": "pushup"})
        assert restart.status_code == 200

        status_after_restart = await ac.get("/session/status")
        assert status_after_restart.status_code == 200
        restart_data = status_after_restart.json()["data"]
        assert restart_data["session_summary"] is None
        assert restart_data["requires_voice_start"] is False

        await ac.post("/session/stop", json={})

        last = await ac.get("/session/last")
        assert last.status_code == 200

        history = await ac.get("/session/history?limit=5")
        assert history.status_code == 200
        history_data = history.json()["data"]
        assert "sessions" in history_data



@pytest.mark.asyncio
async def test_session_voice_event_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        await ac.post("/session/start", json={"exercise": "squat"})

        resp = await ac.post("/session/voice-event", json={"message": "Voz: prueba", "intent": "start"})
        assert resp.status_code == 200
        event = resp.json()["data"]
        assert event["message"] == "Voz: prueba"
        seq = event.get("seq")
        assert isinstance(seq, int) and seq > 0

        status = await ac.get("/session/status")
        assert status.status_code == 200
        voice_event = status.json()["data"].get("voice_event")
        assert voice_event and voice_event.get("message") == "Voz: prueba"

        resp2 = await ac.post("/session/voice-event", json={"message": "Otro comando", "intent": "pause"})
        assert resp2.status_code == 200
        event2 = resp2.json()["data"]
        assert event2.get("seq") == seq + 1

        status2 = await ac.get("/session/status")
        assert status2.status_code == 200
        voice_event2 = status2.json()["data"].get("voice_event")
        assert voice_event2 and voice_event2.get("message") == "Otro comando"

        missing = await ac.post("/session/voice-event", json={})
        assert missing.status_code == 200
        missing_body = missing.json()
        assert missing_body.get("success") is False

        await ac.post("/session/stop", json={})


@pytest.mark.asyncio
async def test_pause_then_start_without_flags_resumes():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/session/start", json={"exercise": "squat"})
        assert r.status_code == 200

        st1 = (await ac.get("/session/status")).json()["data"]
        d1 = st1["duration_sec"]

        # Pause
        rp = await ac.post("/session/pause", json={})
        assert rp.status_code == 200

        st2 = (await ac.get("/session/status")).json()["data"]
        d2 = st2["duration_sec"]
        assert d2 >= d1

        # Call start WITHOUT resume/reset flags to simulate voice "iniciar"
        rs = await ac.post("/session/start", json={})
        assert rs.status_code == 200
        data = rs.json()["data"]
        assert data["status"] == "active"

        # Ensure duration didn't reset to 0; it should resume
        st3 = (await ac.get("/session/status")).json()["data"]
        assert st3["duration_sec"] >= d2

        # And reps are preserved over pause
        reps_before = st1.get("rep_count", 0)
        reps_after = st3.get("rep_count", 0)
        assert reps_after >= reps_before

        await ac.post("/session/stop", json={})

