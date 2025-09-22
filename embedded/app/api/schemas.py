"""Pydantic schemas for request/response payloads.

All endpoints use a standardized JSON envelope: {"success": bool, "data": any, "error": str|None}
"""
from __future__ import annotations

from pydantic import BaseModel, Field
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
    shoulder_hip_alignment: float | None = None


class PostureOutput(BaseModel):
    fps: float
    joints: List[Joint]
    angles: Angles
    quality: float
    feedback: str
    exercise: str | None = None
    phase: str | None = None
    rep_count: int | None = None


class BiometricsInput(BaseModel):
    token: Optional[str] = None  # Fitbit OAuth token, if pushing from app


class BiometricsOutput(BaseModel):
    heart_rate_bpm: int
    steps: int
    timestamp: str


class RoutineInput(BaseModel):
    user_id: str
    performance: Optional[dict] = None  # posture and HR feedback


class RoutineOutput(BaseModel):
    routine_id: str
    blocks: list
    duration_min: int


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
