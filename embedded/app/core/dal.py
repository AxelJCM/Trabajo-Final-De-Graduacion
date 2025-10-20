"""Data access layer utilities."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .models import Token, UserConfig, SessionMetrics, BiometricSample


def init_defaults(db: Session) -> None:
    if not db.query(UserConfig).filter(UserConfig.id == 1).first():
        db.add(UserConfig(id=1))
    db.commit()


def get_user_config(db: Session) -> UserConfig:
    cfg = db.query(UserConfig).filter(UserConfig.id == 1).first()
    if not cfg:
        cfg = UserConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def save_user_config(db: Session, **kwargs) -> UserConfig:
    cfg = get_user_config(db)
    for k, v in kwargs.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def get_tokens(db: Session) -> Optional[Token]:
    """Return tokens if present.

    Falls back to a minimal raw SELECT when legacy DBs lack new columns
    (provider/scope/token_type/timestamps), avoiding OperationalError.
    """
    try:
        return db.query(Token).filter(Token.id == 1).first()
    except Exception:
        try:
            res = db.execute(
                text("SELECT id, access_token, refresh_token, expires_at_utc FROM token WHERE id=1")
            )
            row = res.first()
            if not row:
                return None
            # Build an in-memory Token object with basic fields
            return Token(
                id=row[0], access_token=row[1], refresh_token=row[2], expires_at_utc=row[3]
            )
        except Exception:
            return None


def save_tokens(
    db: Session,
    access_token: str,
    refresh_token: str,
    expires_in: Optional[int] = None,
    *,
    provider: str = "fitbit",
    scope: Optional[str] = None,
    token_type: Optional[str] = None,
    expires_at_utc: Optional[datetime] = None,
) -> Token:
    """Upsert OAuth tokens with optional metadata.

    If ``expires_at_utc`` is not provided, it is computed from ``expires_in``.
    """
    if expires_at_utc is None:
        if expires_in is None:
            expires_in = 3600
        expires_at_utc = datetime.utcnow() + timedelta(seconds=int(expires_in))

    tok = get_tokens(db)
    now = datetime.utcnow()
    if not tok:
        tok = Token(
            id=1,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_utc=expires_at_utc,
            provider=provider,
            scope=scope,
            token_type=token_type,
            created_at_utc=now,
            updated_at_utc=now,
        )
    else:
        tok.access_token = access_token
        tok.refresh_token = refresh_token
        tok.expires_at_utc = expires_at_utc
        tok.provider = provider or tok.provider
        tok.scope = scope or tok.scope
        tok.token_type = token_type or tok.token_type
        tok.updated_at_utc = now
    try:
        db.add(tok)
        db.commit()
        db.refresh(tok)
        return tok
    except OperationalError:
        # Fallback for existing DBs without new columns
        # Ensure row exists
        res = db.execute(text("SELECT id FROM token WHERE id=1"))
        row = res.first()
        if row is None:
            db.execute(
                text(
                    "INSERT INTO token (id, access_token, refresh_token, expires_at_utc) VALUES (1, :a, :r, :e)"
                ),
                {"a": access_token, "r": refresh_token, "e": expires_at_utc},
            )
        else:
            db.execute(
                text(
                    "UPDATE token SET access_token=:a, refresh_token=:r, expires_at_utc=:e WHERE id=1"
                ),
                {"a": access_token, "r": refresh_token, "e": expires_at_utc},
            )
        db.commit()
        # Re-read using ORM (with whatever columns are present)
        tok = get_tokens(db)
        return tok


def add_session_metrics(db: Session, **kwargs) -> SessionMetrics:
    row = SessionMetrics(**kwargs)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except OperationalError:
        db.rollback()
        _ensure_session_metrics_columns(db)
        row = SessionMetrics(**kwargs)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def add_biometric_sample(db: Session, **kwargs) -> BiometricSample:
    row = BiometricSample(**kwargs)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row
    except OperationalError:
        db.rollback()
        _ensure_biometric_sample_columns(db)
        row = BiometricSample(**kwargs)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def get_last_biometric_sample(db: Session) -> Optional[BiometricSample]:
    return (
        db.query(BiometricSample)
        .order_by(BiometricSample.timestamp_utc.desc())
        .first()
    )


def get_biometric_history(db: Session, limit: int = 120) -> list[BiometricSample]:
    q = (
        db.query(BiometricSample)
        .order_by(BiometricSample.timestamp_utc.desc())
        .limit(limit)
    )
    return list(q)


def get_last_session_metrics(db: Session) -> Optional[SessionMetrics]:
    return (
        db.query(SessionMetrics)
        .order_by(SessionMetrics.started_at_utc.desc())
        .first()
    )


def get_session_history(db: Session, limit: int = 20) -> list[SessionMetrics]:
    q = (
        db.query(SessionMetrics)
        .order_by(SessionMetrics.started_at_utc.desc())
        .limit(limit)
    )
    return list(q)


def _ensure_session_metrics_columns(db: Session) -> None:
    try:
        res = db.execute(text("PRAGMA table_info(session_metrics)"))
    except Exception:
        return
    existing = {row[1] for row in res}  # type: ignore[index]
    migrations = [
        ("ended_at_utc", "ALTER TABLE session_metrics ADD COLUMN ended_at_utc DATETIME"),
        ("duration_active_sec", "ALTER TABLE session_metrics ADD COLUMN duration_active_sec INTEGER DEFAULT 0"),
        ("total_reps", "ALTER TABLE session_metrics ADD COLUMN total_reps INTEGER DEFAULT 0"),
        ("exercise", "ALTER TABLE session_metrics ADD COLUMN exercise VARCHAR"),
    ]
    for name, ddl in migrations:
        if name not in existing:
            db.execute(text(ddl))
    db.commit()


def _ensure_biometric_sample_columns(db: Session) -> None:
    try:
        res = db.execute(text("PRAGMA table_info(biometric_sample)"))
    except Exception:
        return
    existing = {row[1] for row in res}  # type: ignore[index]
    migrations = [
        ("status_icon", "ALTER TABLE biometric_sample ADD COLUMN status_icon VARCHAR"),
        ("status_message", "ALTER TABLE biometric_sample ADD COLUMN status_message VARCHAR"),
    ]
    for name, ddl in migrations:
        if name not in existing:
            db.execute(text(ddl))
    db.commit()
