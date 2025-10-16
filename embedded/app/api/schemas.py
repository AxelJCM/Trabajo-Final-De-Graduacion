"""Pydantic schemas for request/response payloads.

All endpoints use a standardized JSON envelope: {"success": bool, "data": any, "error": str|None}
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List


class Envelope(BaseModel):
    success: bool = True
    data: Optional[dict] = None
    error: Optional[str] = None


class PostureInput(BaseModel):
    # Placeholder for posture frame id or features if sent by client
    frame_id: Optional[str] = None


class Joint(BaseModel):
    name: str
    x: float
    y: float
    z: float = 0.0
    score: float = Field(ge=0.0, le=1.0, default=1.0)


class Angles(BaseModel):
    left_elbow: float | None = None
    right_elbow: float | None = None
    left_knee: float | None = None
    right_knee: float | None = None
    left_hip: float | None = None
    right_hip: float | None = None
    shoulder_hip_alignment: float | None = None
    torso_forward: float | None = None


class PostureOutput(BaseModel):
    fps: float
    latency_ms: float | None = None
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    joints: List[Joint]
    angles: Angles
    quality: float
    quality_avg: float | None = None
    feedback: str
    feedback_code: str | None = None
    exercise: str | None = None
    phase: str | None = None
    phase_label: str | None = None
    rep_count: int | None = None
    current_exercise_reps: int | None = None
    rep_totals: dict[str, int] | None = None
    timestamp_utc: float | None = None


class BiometricsInput(BaseModel):
    token: Optional[str] = None  # Fitbit OAuth token, if pushing from app


class BiometricsOutput(BaseModel):
    heart_rate_bpm: int
    steps: int
    timestamp_utc: str
    heart_rate_source: str
    steps_source: str
    zone_name: str | None = None
    zone_label: str | None = None
    zone_color: str | None = None
    intensity: float | None = None
    fitbit_status: str
    fitbit_status_level: str
    fitbit_status_icon: str
    fitbit_status_message: str | None = None
    staleness_sec: float | None = None
    error: str | None = None


class SessionMetricsOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int = Field(alias="id")
    started_at_utc: datetime
    ended_at_utc: datetime | None = None
    duration_sec: int
    duration_active_sec: int
    avg_hr: int
    max_hr: int
    avg_quality: float
    total_reps: int
    exercise: str | None = None


# Routine schemas removed (scope reduction)


class ConfigInput(BaseModel):
    language: Optional[str] = None
    intensity: Optional[str] = None
    units: Optional[str] = None
    tz: Optional[str] = None


class ConfigOutput(BaseModel):
    language: str
    intensity: str
    units: str
    tz: str
