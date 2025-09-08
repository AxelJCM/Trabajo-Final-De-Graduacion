"""Fitbit OAuth2 endpoints: login and callback.

Builds auth URL and exchanges code for tokens, stored via TokenStore.
"""
from __future__ import annotations

import base64
import urllib.parse

import requests
from fastapi import APIRouter, Response
from loguru import logger

from app.core.config import get_settings
from app.biometrics.token_store import TokenStore, FitbitTokens

router = APIRouter()


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
def fitbit_callback(code: str) -> dict:
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
        tokens = FitbitTokens(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            token_type=payload.get("token_type", "Bearer"),
            expires_in=payload.get("expires_in", 28800),
        )
        TokenStore().save(tokens)
        logger.info("Fitbit tokens saved")
        return {"success": True}
    except Exception as exc:  # pragma: no cover
        logger.error("Fitbit callback error: {}", exc)
        return {"success": False, "error": str(exc)}


@router.post("/auth/fitbit/refresh")
def fitbit_refresh() -> dict:
    """Refresh tokens using the stored refresh_token."""
    s = get_settings()
    tokens = TokenStore().load()
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
        new_tokens = FitbitTokens(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            token_type=payload.get("token_type", "Bearer"),
            expires_in=payload.get("expires_in", 28800),
        )
        TokenStore().save(new_tokens)
        logger.info("Fitbit tokens refreshed")
        return {"success": True}
    except Exception as exc:  # pragma: no cover
        logger.error("Fitbit refresh error: {}", exc)
        return {"success": False, "error": str(exc)}
