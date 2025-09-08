from __future__ import annotations

from httpx import AsyncClient

from app.api.main import app


async def test_fitbit_login_redirect():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/auth/fitbit/login")
    assert r.status_code in (302, 307)
    assert "Location" in r.headers