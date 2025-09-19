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
    duration_sec = Column(Integer, default=0)
    avg_hr = Column(Integer, default=0)
    max_hr = Column(Integer, default=0)
    avg_quality = Column(Float, default=0.0)
