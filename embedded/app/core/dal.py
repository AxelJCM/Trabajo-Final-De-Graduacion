"""Data access layer utilities."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .models import Token, UserConfig, SessionMetrics


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
    return db.query(Token).filter(Token.id == 1).first()


def save_tokens(db: Session, access_token: str, refresh_token: str, expires_in: int) -> Token:
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    tok = get_tokens(db)
    if not tok:
        tok = Token(id=1, access_token=access_token, refresh_token=refresh_token, expires_at_utc=expires_at)
    else:
        tok.access_token = access_token
        tok.refresh_token = refresh_token
        tok.expires_at_utc = expires_at
    db.add(tok)
    db.commit()
    db.refresh(tok)
    return tok


def add_session_metrics(db: Session, **kwargs) -> SessionMetrics:
    row = SessionMetrics(**kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
