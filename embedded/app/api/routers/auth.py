"""Fitbit OAuth2 endpoints: login and callback.

Builds auth URL and exchanges code for tokens, stored via TokenStore.
Supports optional redirect override passed via `state` so the
`redirect_uri` used in token exchange matches the authorize step.
"""
from __future__ import annotations

import base64
import json
import urllib.parse

import requests
from fastapi import APIRouter, Response, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from app.core.config import get_settings
from sqlalchemy.orm import Session
from app.core.db import get_db, Base, engine
from app.core.dal import save_tokens, get_tokens

router = APIRouter()
Base.metadata.create_all(bind=engine)


@router.get("/auth/fitbit/login")
def fitbit_login(request: Request, redirect: str | None = None) -> Response:
    s = get_settings()
    client_id = s.fitbit_client_id
    redirect_uri = s.fitbit_redirect_uri
    scope = "heartrate profile activity"
    state_obj = {}
    if redirect:
        state_obj["r"] = redirect
        redirect_uri = redirect
    state = base64.urlsafe_b64encode(json.dumps(state_obj).encode()).decode() if state_obj else None
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    # Fallback: if no redirect provided and no configured redirect, infer from request
    if not redirect and not s.fitbit_redirect_uri:
        try:
            inferred = str(request.url_for("fitbit_callback"))
            params["redirect_uri"] = inferred
            redirect_uri = inferred
        except Exception:
            pass
    # Guard: ensure client_id is configured
    if not client_id:
        from fastapi.responses import HTMLResponse
        html = (
            "<h3>Fitbit setup required</h3>"
            "<p>Missing <code>FITBIT_CLIENT_ID</code>. Set it in <code>embedded/.env</code> and restart the server.</p>"
            "<p>Also set <code>FITBIT_CLIENT_SECRET</code> and, if needed, <code>FITBIT_REDIRECT_URI</code> to your registered callback, e.g. <code>http://&lt;PI_IP&gt;:8000/auth/fitbit/callback</code>.</p>"
        )
        return HTMLResponse(html, status_code=400)
    url = "https://www.fitbit.com/oauth2/authorize?" + urllib.parse.urlencode(params)
    return Response(status_code=302, headers={"Location": url})


@router.get("/auth/fitbit/callback")
def fitbit_callback(code: str, state: str | None = None, db: Session = Depends(get_db)):
    s = get_settings()
    token_url = "https://api.fitbit.com/oauth2/token"
    auth_hdr = base64.b64encode(f"{s.fitbit_client_id}:{s.fitbit_client_secret}".encode()).decode()
    # Use configured redirect by default; allow override if provided in state
    redirect_uri = s.fitbit_redirect_uri
    if state:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            if isinstance(decoded, dict) and decoded.get("r"):
                redirect_uri = str(decoded["r"])
        except Exception:
            pass
    data = {
        "client_id": s.fitbit_client_id,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
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
        if r.status_code >= 400:
            # Return more details to help diagnose (invalid_client, invalid_grant, redirect mismatch, etc.)
            logger.error("Fitbit callback token error: {} {}", r.status_code, r.text[:500])
            body_safe = (r.text or "").replace("<", "&lt;").replace(">", "&gt;")
            html = f"""
            <h3>Fitbit: token exchange failed</h3>
            <p>Status: {r.status_code}</p>
            <pre style='white-space:pre-wrap'>{body_safe[:2000]}</pre>
            <p>Tips:
              <ul>
                <li>Verifica que la Redirect URI registrada en Fitbit coincida exactamente con esta: <code>{redirect_uri}</code></li>
                <li>Comprueba FITBIT_CLIENT_ID/FITBIT_CLIENT_SECRET en embedded/.env</li>
              </ul>
            </p>
            <p><a href='/debug/view'>Volver al stream</a></p>
            """
            return HTMLResponse(html, status_code=400)
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
        # Redirect to a friendly page instead of raw JSON
        return RedirectResponse(url="/debug/view?fitbit=connected", status_code=302)
    except Exception as exc:  # pragma: no cover
        logger.error("Fitbit callback error: {}", exc)
        html = f"""
        <h3>Fitbit: unexpected error</h3>
        <pre>{str(exc)}</pre>
        <p><a href='/debug/view'>Volver al stream</a></p>
        """
        return HTMLResponse(html, status_code=500)


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
        "client_id": s.fitbit_client_id,
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
        if r.status_code >= 400:
            logger.error("Fitbit refresh token error: {} {}", r.status_code, r.text[:500])
            return {"success": False, "status": r.status_code, "body": r.text}
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
