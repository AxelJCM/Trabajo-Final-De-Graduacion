from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.main import app


@pytest.mark.asyncio
async def test_training_voice_sample(monkeypatch):
    captured = {}

    async def fake_post(url, json, headers=None):
        pass

    paths = []

    def fake_save_voice_sample(transcript, intent, audio_path=None, metadata=None):
        paths.append((transcript, intent, audio_path, metadata))
        from pathlib import Path
        return Path(f"/tmp/{intent}_sample.json")

    monkeypatch.setattr("app.api.routers.training.save_voice_sample", fake_save_voice_sample)
    monkeypatch.setattr("app.api.routers.training.register_voice_synonym", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.routers.training.refresh_commands_cache", lambda: None)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/training/voice/sample",
            json={"transcript": "iniciar", "intent": "start", "add_synonym": True},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["intent"] == "start"
    assert paths


@pytest.mark.asyncio
async def test_training_pose_sample(monkeypatch):
    from app.api.routers.training import pose_estimator

    def fake_save_pose_sample(label, joints, angles, metadata=None):
        from pathlib import Path
        return Path(f"/tmp/{label}.json")

    monkeypatch.setattr("app.api.routers.training.save_pose_sample", fake_save_pose_sample)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/training/pose/sample", json={"label": "sentadilla"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "path" in body["data"]
