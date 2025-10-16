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
    assert d["latency_ms"] is not None
    assert d["latency_ms_p50"] is not None
    assert d["latency_ms_p95"] is not None
    assert "rep_totals" in d and isinstance(d["rep_totals"], dict)
    assert "feedback_code" in d and isinstance(d["feedback_code"], str)
    assert "phase_label" in d and isinstance(d["phase_label"], str)
    assert "quality_avg" in d
    assert "current_exercise_reps" in d
    assert "frame_b64" in d
    if d["frame_b64"] is not None:
        assert isinstance(d["frame_b64"], str)
