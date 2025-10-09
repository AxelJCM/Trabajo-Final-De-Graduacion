"""Fitbit OAuth2 endpoints: login and callback.

Builds auth URL and exchanges code for tokens, stored via TokenStore.
Supports optional redirect override passed via `state` so the
`redirect_uri` used in token exchange matches the authorize step.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import os
import hashlib
import secrets

import requests
from requests.auth import HTTPBasicAuth
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
def fitbit_login(request: Request, redirect: str | None = None, auth_mode: str | None = None, force_prompt: bool | None = None) -> Response:
    s = get_settings()
    # Sanitize env values
    client_id = (s.fitbit_client_id or "").strip().strip('"').strip("'")
    client_secret = (s.fitbit_client_secret or "").strip().strip('"').strip("'")
    redirect_uri = s.fitbit_redirect_uri
    scope = "heartrate profile activity"
    state_obj = {}
    # Enable PKCE if no client_secret is configured or explicitly requested
    use_pkce = (not client_secret) or (os.getenv("FITBIT_USE_PKCE", "0") in {"1","true","TRUE","yes","on"})
    code_verifier = None
    code_challenge = None
    if use_pkce:
        # RFC 7636: code_verifier 43-128 chars, unreserved. We'll use base64url of 64 random bytes, stripped '='
        rnd = secrets.token_urlsafe(64)
        code_verifier = rnd[:128]
        # S256 challenge
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
    if redirect:
        state_obj["r"] = redirect
        redirect_uri = redirect
    if code_verifier:
        state_obj["cv"] = code_verifier  # return via state for callback
        state_obj["pk"] = True
    if auth_mode:
        state_obj["am"] = auth_mode.lower()  # pass-through to callback
    state = base64.urlsafe_b64encode(json.dumps(state_obj).encode()).decode() if state_obj else None
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
    }
    # Force Fitbit to re-show login/consent when requested or for troubleshooting
    if force_prompt or os.getenv("FITBIT_FORCE_PROMPT", "0") in {"1","true","TRUE","yes","on"}:
        params["prompt"] = "login consent"
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
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
    # Sanitize env values to avoid stray quotes/whitespace issues from .env
    cid = (s.fitbit_client_id or "").strip().strip('"').strip("'")
    csec = (s.fitbit_client_secret or "").strip().strip('"').strip("'")
    use_pkce = False
    code_verifier = None
    auth_mode_override: str | None = None
    # Use configured redirect by default; allow override if provided in state
    redirect_uri = s.fitbit_redirect_uri
    if state:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            if isinstance(decoded, dict) and decoded.get("r"):
                redirect_uri = str(decoded["r"])
            if isinstance(decoded, dict) and decoded.get("cv"):
                code_verifier = str(decoded.get("cv"))
                use_pkce = True
            if isinstance(decoded, dict) and decoded.get("pk"):
                use_pkce = True
            if isinstance(decoded, dict) and decoded.get("am"):
                try:
                    auth_mode_override = str(decoded.get("am")).lower()
                except Exception:
                    auth_mode_override = None
        except Exception:
            pass
    data = {
        "client_id": cid,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth_obj = None
    if use_pkce:
        if not code_verifier:
            # As a fallback, allow env-provided verifier for testing (not recommended)
            code_verifier = os.getenv("FITBIT_CODE_VERIFIER")
        if not code_verifier:
            body_safe = "Missing code_verifier for PKCE flow"
            html = f"""
            <h3>Fitbit: token exchange failed</h3>
            <pre>{body_safe}</pre>
            <p><a href='/debug/view'>Volver al stream</a></p>
            """
            return HTMLResponse(html, status_code=400)
        data["code_verifier"] = code_verifier
        # Do NOT send Authorization header for public client PKCE
    else:
        # Confidential client: prefer HTTP Basic auth; optionally include client_secret in body
    auth_mode = (auth_mode_override or os.getenv("FITBIT_AUTH_MODE", "basic")).lower()  # basic | body | both
        if not csec:
            logger.error("Fitbit confidential flow without client_secret configured")
            html = (
                "<h3>Fitbit: configuración incompleta</h3>"
                "<p>Falta <code>FITBIT_CLIENT_SECRET</code> para el flujo Confidential.</p>"
                "<p>Opciones: agregue el secret en embedded/.env o use FITBIT_USE_PKCE=1 para flujo Public (PKCE).</p>"
                "<p><a href='/debug/view'>Volver al stream</a></p>"
            )
            return HTMLResponse(html, status_code=400)
        if csec and auth_mode in {"basic", "both"}:
            auth_obj = HTTPBasicAuth(cid, csec)
        if csec and auth_mode in {"body", "both"}:
            data["client_secret"] = csec
    # Log safe diagnostics about auth selection
    try:
        logger.info(
            "Fitbit token exchange: pkce={}, auth_mode={}, redirect_uri={}",
            use_pkce,
            (os.getenv("FITBIT_AUTH_MODE", "basic").lower()),
            redirect_uri,
        )
    except Exception:
        pass
    try:
        r = requests.post(
            token_url,
            headers=headers,
            data=data,
            auth=auth_obj,
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
    cid = (s.fitbit_client_id or "").strip().strip('"').strip("'")
    csec = (s.fitbit_client_secret or "").strip().strip('"').strip("'")
    auth_hdr = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens.refresh_token,
        "client_id": cid,
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


@router.get("/auth/fitbit/debug-config")
def fitbit_debug_config(request: Request) -> dict:
    """Return safe diagnostics about OAuth configuration without exposing secrets.

    Includes lengths, hashes, mode selection, and redirect URI that will be used.
    """
    raw_cid = os.getenv("FITBIT_CLIENT_ID", "")
    raw_csec = os.getenv("FITBIT_CLIENT_SECRET", "")
    raw_redirect = os.getenv("FITBIT_REDIRECT_URI", "")

    # Sanitized values (same logic as callback/login)
    cid = (raw_cid or "").strip().strip('"').strip("'")
    csec = (raw_csec or "").strip().strip('"').strip("'")
    redirect_uri = (raw_redirect or "").strip()

    # Infer redirect if missing
    if not redirect_uri:
        try:
            redirect_uri = str(request.url_for("fitbit_callback"))
        except Exception:
            redirect_uri = None

    import hashlib as _hashlib
    def _sha8(s: str | None) -> str | None:
        if not s:
            return None
        return _hashlib.sha256(s.encode()).hexdigest()[:8]

    def _has_nonprintable(s: str) -> bool:
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in s)

    use_pkce = (not csec) or (os.getenv("FITBIT_USE_PKCE", "0") in {"1","true","TRUE","yes","on"})
    auth_mode = os.getenv("FITBIT_AUTH_MODE", "both").lower()

    return {
        "client_id_len": len(cid),
        "client_id_suffix": cid[-4:] if cid else None,
        "client_secret_len": len(csec) if csec else 0,
        "client_secret_sha256_8": _sha8(csec),
        "client_id_trimmed_delta": len(raw_cid) - len(cid) if raw_cid else 0,
        "client_secret_trimmed_delta": len(raw_csec) - len(csec) if raw_csec else 0,
        "client_secret_has_nonprintable": _has_nonprintable(csec) if csec else False,
        "using_pkce": use_pkce,
        "fitbit_auth_mode": auth_mode,
        "redirect_uri": redirect_uri,
    }


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
