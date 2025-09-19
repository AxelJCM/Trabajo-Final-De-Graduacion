"""Fitbit OAuth2 endpoints: login and callback.

Builds auth URL and exchanges code for tokens, stored via TokenStore.
"""
from __future__ import annotations

import base64
import urllib.parse

import requests
from fastapi import APIRouter, Response, Depends
from loguru import logger

from app.core.config import get_settings
from sqlalchemy.orm import Session
from app.core.db import get_db, Base, engine
from app.core.dal import save_tokens, get_tokens

router = APIRouter()
Base.metadata.create_all(bind=engine)


@router.get("/auth/fitbit/login")
def fitbit_login() -> Response:
    s = get_settings()
    client_id = s.fitbit_client_id
    redirect_uri = s.fitbit_redirect_uri
    scope = "heartrate profile activity"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
    }
    url = "https://www.fitbit.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    return Response(status_code=302, headers={"Location": url})


@router.get("/auth/fitbit/callback")
def fitbit_callback(code: str, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    token_url = "https://api.fitbit.com/oauth2/token"
    auth_hdr = base64.b64encode(f"{s.fitbit_client_id}:{s.fitbit_client_secret}".encode()).decode()
    data = {
        "client_id": s.fitbit_client_id,
        "grant_type": "authorization_code",
        "redirect_uri": s.fitbit_redirect_uri,
        "code": code,
    }
    try:
        r = requests.post(
            token_url,
            headers={
                "Authorization": f"Basic {auth_hdr}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        save_tokens(
            db,
            payload.get("access_token"),
            payload.get("refresh_token"),
            payload.get("expires_in", 28800),
            provider="fitbit",
            scope=payload.get("scope"),
            token_type=payload.get("token_type"),
        )
        logger.info("Fitbit tokens saved")
        return {"success": True}
    except Exception as exc:  # pragma: no cover
        logger.error("Fitbit callback error: {}", exc)
        return {"success": False, "error": str(exc)}


@router.post("/auth/fitbit/refresh")
def fitbit_refresh(db: Session = Depends(get_db)) -> dict:
    """Refresh tokens using the stored refresh_token."""
    s = get_settings()
    tokens = get_tokens(db)
    if not tokens:
        return {"success": False, "error": "no_tokens"}
    token_url = "https://api.fitbit.com/oauth2/token"
    auth_hdr = base64.b64encode(f"{s.fitbit_client_id}:{s.fitbit_client_secret}".encode()).decode()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens.refresh_token,
    }
    try:
        r = requests.post(
            token_url,
            headers={
                "Authorization": f"Basic {auth_hdr}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        save_tokens(
            db,
            payload.get("access_token"),
            payload.get("refresh_token"),
            payload.get("expires_in", 28800),
            provider="fitbit",
            scope=payload.get("scope"),
            token_type=payload.get("token_type"),
        )
        logger.info("Fitbit tokens refreshed")
        return {"success": True}
    except Exception as exc:  # pragma: no cover
        logger.error("Fitbit refresh error: {}", exc)
        return {"success": False, "error": str(exc)}


@router.get("/auth/fitbit/status")
def fitbit_status(db: Session = Depends(get_db)) -> dict:
    tok = get_tokens(db)
    if not tok:
        return {"connected": False}
    from datetime import datetime, timezone
    remaining = None
    if getattr(tok, "expires_at_utc", None):
        try:
            remaining = (tok.expires_at_utc - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            remaining = None
    return {
        "connected": True,
        "provider": tok.provider,
        "expires_at_utc": tok.expires_at_utc.isoformat() if tok.expires_at_utc else None,
        "scope": tok.scope,
        "token_type": tok.token_type,
        "seconds_to_expiry": remaining,
    }
