from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List

import pytest

try:
    from app.biometrics import fitbit_client as fitbit_module
    from app.biometrics.fitbit_client import FitbitClient
except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing during CI
    pytest.skip(f"Fitbit client dependencies missing: {exc}", allow_module_level=True)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, queue: List[_FakeResponse]):
        self._queue = queue

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        return None

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        if not self._queue:
            raise AssertionError(f"Unexpected request to {url}")
        return self._queue.pop(0)


@pytest.mark.asyncio
async def test_fitbit_client_uses_intraday_dataset(monkeypatch):
    queue: List[_FakeResponse] = [
        _FakeResponse(
            200,
            {
                "activities-heart": [],
                "activities-heart-intraday": {
                    "dataset": [
                        {"time": "12:00:00", "value": 82},
                        {"time": "12:00:01", "value": 84},
                    ],
                },
            },
        ),
        _FakeResponse(
            200,
            {"activities-steps": [{"dateTime": "2024-10-10", "value": "4321"}]},
        ),
    ]

    def _make_client(*args, **kwargs):
        return _FakeAsyncClient(queue)

    monkeypatch.setattr(fitbit_module.httpx, "AsyncClient", _make_client)

    client = FitbitClient(
        access_token="token",
        refresh_token="refresh",
        expires_at_utc=datetime.utcnow() + timedelta(seconds=30),
    )
    # Expiry should be normalized to timezone-aware
    assert client.expires_at_utc is not None
    assert client.expires_at_utc.tzinfo is not None

    metrics = await client.get_latest_metrics()

    assert metrics.heart_rate_bpm == 84
    assert metrics.steps == 4321
    assert metrics.heart_rate_source == "intraday"
    assert metrics.steps_source in {"intraday", "daily", "cached"}
    assert metrics.timestamp_utc.tzinfo is not None
    assert metrics.error is None
    assert metrics.zone_name is not None
    assert metrics.fitbit_status_level in {"green", "yellow", "red"}
    assert metrics.fitbit_status_icon in {"[OK]", "[!]", "[X]"}
    assert queue == []

    cached_client = FitbitClient()
    cached_metrics = cached_client.get_cached_metrics()
    assert cached_metrics is not None
    assert cached_metrics.fitbit_status_icon in {"[OK]", "[!]", "[X]", "[?]"}


@pytest.mark.asyncio
async def test_fitbit_client_falls_back_to_summary(monkeypatch):
    queue: List[_FakeResponse] = [
        _FakeResponse(
            200,
            {
                "activities-heart": [
                    {
                        "dateTime": "2024-10-10",
                        "value": {
                            "restingHeartRate": 61,
                            "heartRateZones": [
                                {"name": "Out of Range", "min": 30, "minutes": 800},
                                {"name": "Fat Burn", "min": 91, "minutes": 10},
                            ],
                        },
                    }
                ],
            },
        ),
        _FakeResponse(
            200,
            {"activities-steps": [{"dateTime": "2024-10-10", "value": "1000"}]},
        ),
    ]

    def _make_client(*args, **kwargs):
        return _FakeAsyncClient(queue)

    monkeypatch.setattr(fitbit_module.httpx, "AsyncClient", _make_client)

    client = FitbitClient(
        access_token="token",
        refresh_token="refresh",
        expires_at_utc=datetime.utcnow() + timedelta(seconds=30),
    )

    metrics = await client.get_latest_metrics()

    assert metrics.heart_rate_bpm == 61
    assert metrics.steps == 1000
    assert metrics.heart_rate_source == "summary"
    assert metrics.steps_source in {"intraday", "daily", "cached"}
    assert metrics.timestamp_utc.tzinfo is not None
    assert metrics.zone_name is not None
    assert metrics.fitbit_status_level in {"green", "yellow", "red"}
    assert metrics.fitbit_status_icon in {"[OK]", "[!]", "[X]"}
    assert queue == []
