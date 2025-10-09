from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from .config import get_settings
from .token_store import load_tokens, save_tokens
from .fitbit_client import FitbitClient

app = FastAPI(title="Fitbit Prototype")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/view", status_code=302)


@app.get("/view")
def view() -> HTMLResponse:
    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8'/>
        <title>Fitbit Prototype</title>
        <style>body{font-family:sans-serif;margin:20px} .btn{padding:8px 12px;background:#1976d2;color:#fff;text-decoration:none;border-radius:4px} .ok{color:#2e7d32} .err{color:#c62828}</style>
      </head>
      <body>
        <h3>Fitbit Prototype</h3>
        <p><a class='btn' href='/auth/fitbit/login'>Connect Fitbit</a>
           <a class='btn' href='/fitbit/last' target='_blank'>Read HR/Steps</a></p>
        <div id='status'>Checking…</div>
        <script>
          async function load(){
            try{
              const r = await fetch('/fitbit/status', {cache:'no-store'});
              const d = await r.json();
              const el = document.getElementById('status');
              if(d.connected){ el.innerHTML = '<b class="ok">Fitbit conectado</b>' }
              else { el.innerHTML = '<span class="err">Fitbit no conectado</span>' }
            }catch(e){ }
          }
          load(); setInterval(load, 4000);
          (function(){
            const sp = new URLSearchParams(window.location.search);
            if (sp.has('code')){
              const code = sp.get('code');
              const state = sp.get('state') || '';
              const url = '/auth/fitbit/callback?code=' + encodeURIComponent(code) + (state?('&state='+encodeURIComponent(state)):'');
              window.location.replace(url);
            }
          })();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/auth/fitbit/login")
def fitbit_login(redirect: Optional[str] = None):
    s = get_settings()
    cid = (s.fitbit_client_id or '').strip().strip('"').strip("'")
    csec = (s.fitbit_client_secret or '').strip().strip('"').strip("'")
    redirect_uri = redirect or s.fitbit_redirect_uri
    scope = "heartrate profile activity"
    state_obj: dict = {}

    # PKCE si no hay secret
    use_pkce = (not csec) or (os.getenv("FITBIT_USE_PKCE", "1") in {"1","true","TRUE","yes","on"})
    code_verifier = None
    code_challenge = None
    if use_pkce:
        ver = base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip('=')
        code_verifier = ver[:128]
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
        state_obj["cv"] = code_verifier
        state_obj["pk"] = True
    if redirect and redirect != s.fitbit_redirect_uri:
        state_obj["r"] = redirect

    state = base64.urlsafe_b64encode(json.dumps(state_obj).encode()).decode() if state_obj else None
    params = {
        "client_id": cid,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    if state:
        params["state"] = state
    from urllib.parse import urlencode
    url = "https://www.fitbit.com/oauth2/authorize?" + urlencode(params)
    return RedirectResponse(url=url, status_code=302)


@app.get("/auth/fitbit/callback")
def fitbit_callback(code: str, state: Optional[str] = None):
    import httpx
    s = get_settings()
    cid = (s.fitbit_client_id or '').strip().strip('"').strip("'")
    csec = (s.fitbit_client_secret or '').strip().strip('"').strip("'")
    redirect_uri = s.fitbit_redirect_uri
    code_verifier = None
    use_pkce = False

    if state:
        try:
            obj = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            if obj.get('r'):
                redirect_uri = obj['r']
            if obj.get('cv'):
                code_verifier = obj['cv']
                use_pkce = True
            if obj.get('pk'):
                use_pkce = True
        except Exception:
            pass

    data = {
        "client_id": cid,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth = None
    if use_pkce:
        if not code_verifier:
            return HTMLResponse("<h3>Missing PKCE code_verifier</h3>", status_code=400)
        data["code_verifier"] = code_verifier
    else:
        if not csec:
            return HTMLResponse("<h3>Missing client_secret for confidential flow</h3>", status_code=400)
        auth = httpx.BasicAuth(cid, csec)

    with httpx.Client(timeout=10) as client:
        r = client.post("https://api.fitbit.com/oauth2/token", data=data, headers=headers, auth=auth)
        if r.status_code >= 400:
            body = r.text.replace('<','&lt;').replace('>','&gt;')
            return HTMLResponse(f"<h3>Fitbit token error {r.status_code}</h3><pre>{body[:2000]}</pre>", status_code=400)
        b = r.json()
        save_tokens(b.get('access_token'), b.get('refresh_token'), int(b.get('expires_in', 3600)), b.get('scope'), b.get('token_type'))
    return RedirectResponse(url="/view", status_code=302)


@app.post("/fitbit/refresh")
async def fitbit_refresh():
    c = FitbitClient()
    await c.refresh()
    return {"success": True}


@app.get("/fitbit/status")
def fitbit_status():
    t = load_tokens()
    if not t:
        return {"connected": False}
    left = (t.expires_at_utc - datetime.now(datetime.now().astimezone().tzinfo)).total_seconds()
    return {
        "connected": True,
        "expires_at_utc": t.expires_at_utc.isoformat(),
        "seconds_to_expiry": left,
        "scope": t.scope,
        "token_type": t.token_type,
    }


@app.get("/fitbit/last")
async def fitbit_last():
    c = FitbitClient()
    m = await c.get_metrics()
    return {"success": True, "data": {"heart_rate_bpm": m.heart_rate_bpm, "steps": m.steps}}
