"""ORM models for persistence."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float

from .db import Base


class Token(Base):
    __tablename__ = "token"

    id = Column(Integer, primary_key=True, default=1)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at_utc = Column(DateTime, nullable=False)
    provider = Column(String, default="fitbit")
    scope = Column(String, nullable=True)
    token_type = Column(String, nullable=True)
    created_at_utc = Column(DateTime, default=datetime.utcnow)
    updated_at_utc = Column(DateTime, default=datetime.utcnow)


class UserConfig(Base):
    __tablename__ = "user_config"

    id = Column(Integer, primary_key=True, default=1)
    language = Column(String, default="es")
    intensity = Column(String, default="medium")
    units = Column(String, default="metric")
    tz = Column(String, default="America/Costa_Rica")


class SessionMetrics(Base):
    __tablename__ = "session_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at_utc = Column(DateTime, default=datetime.utcnow)
    ended_at_utc = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, default=0)
    duration_active_sec = Column(Integer, default=0)
    avg_hr = Column(Integer, default=0)
    max_hr = Column(Integer, default=0)
    avg_quality = Column(Float, default=0.0)
    total_reps = Column(Integer, default=0)
    exercise = Column(String, nullable=True)


class BiometricSample(Base):
    __tablename__ = "biometric_sample"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp_utc = Column(DateTime, default=datetime.utcnow, index=True)
    heart_rate_bpm = Column(Integer, default=0)
    steps = Column(Integer, default=0)
    heart_rate_source = Column(String, default="mock")
    steps_source = Column(String, default="mock")
    zone_name = Column(String, nullable=True)
    zone_label = Column(String, nullable=True)
    zone_color = Column(String, nullable=True)
    intensity = Column(Float, default=0.0)
    status = Column(String, default="offline")
    status_level = Column(String, default="yellow")
    status_icon = Column(String, nullable=True)
    status_message = Column(String, nullable=True)
