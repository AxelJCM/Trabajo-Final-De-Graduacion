from __future__ import annotations

from fastapi import APIRouter, Response, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse, JSONResponse
from typing import Iterator
from pathlib import Path
import time
from datetime import datetime, timezone
import json

from app.api.routers.posture import pose_estimator
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.dal import get_tokens

router = APIRouter()

# Exports directory helper
def _exports_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "exports"


def mjpeg_frames(overlay: bool = True, app_state=None) -> Iterator[bytes]:
    cap = pose_estimator.cap
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    if cap is None:
        # placeholder black frame when no camera
        placeholder = np.zeros((360, 640, 3), dtype=np.uint8)
        ok, buf = cv2.imencode('.jpg', placeholder)
        jpg = buf.tobytes() if ok else b""
        while True:
            time.sleep(0.5)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
    else:
        # Landmark index to name mapping (subset used by our pipeline)
        idx_to_name = {
            11: "LEFT_SHOULDER",
            12: "RIGHT_SHOULDER",
            13: "LEFT_ELBOW",
            14: "RIGHT_ELBOW",
            15: "LEFT_WRIST",
            16: "RIGHT_WRIST",
            23: "LEFT_HIP",
            24: "RIGHT_HIP",
            25: "LEFT_KNEE",
            26: "RIGHT_KNEE",
            27: "LEFT_ANKLE",
            28: "RIGHT_ANKLE",
        }
        # Skeleton connections as pairs of names
        edges = [
            ("LEFT_SHOULDER", "RIGHT_SHOULDER"),
            ("LEFT_HIP", "RIGHT_HIP"),
            ("LEFT_SHOULDER", "LEFT_ELBOW"),
            ("LEFT_ELBOW", "LEFT_WRIST"),
            ("RIGHT_SHOULDER", "RIGHT_ELBOW"),
            ("RIGHT_ELBOW", "RIGHT_WRIST"),
            ("LEFT_HIP", "LEFT_KNEE"),
            ("LEFT_KNEE", "LEFT_ANKLE"),
            ("RIGHT_HIP", "RIGHT_KNEE"),
            ("RIGHT_KNEE", "RIGHT_ANKLE"),
            ("LEFT_SHOULDER", "LEFT_HIP"),
            ("RIGHT_SHOULDER", "RIGHT_HIP"),
        ]

        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.1)
                continue

            if overlay and pose_estimator.pose is not None:
                try:
                    h, w = frame.shape[:2]
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    t0 = time.time()
                    result = pose_estimator.pose.process(img_rgb)
                    dt = time.time() - t0
                    # Record latency sample for metrics
                    try:
                        pose_estimator._record_latency(dt)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    if result and result.pose_landmarks:
                        # Collect normalized landmarks into pixel dict
                        pts = {}
                        for idx, lm in enumerate(result.pose_landmarks.landmark):
                            name = idx_to_name.get(idx)
                            if not name:
                                continue
                            x = int(lm.x * w)
                            y = int(lm.y * h)
                            pts[name] = (x, y)
                        # Draw edges
                        for a, b in edges:
                            if a in pts and b in pts:
                                cv2.line(frame, pts[a], pts[b], (0, 255, 255), 2)
                        # Draw joints
                        for name, (x, y) in pts.items():
                            cv2.circle(frame, (x, y), 4, (0, 150, 255), -1)
                        # HUD: reps and phase
                        hud = f"{pose_estimator.exercise} | reps: {pose_estimator.rep_count} | phase: {pose_estimator.phase}"
                        cv2.rectangle(frame, (10, 10), (10 + 420, 40), (0, 0, 0), -1)
                        cv2.putText(frame, hud, (18, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)
                        # Overlay simple performance metrics
                        try:
                            p50, p95 = pose_estimator.get_latency_p50_p95_ms()
                            fps_avg = pose_estimator.get_fps_avg()
                            overlay_txt = f"fps:{fps_avg:.1f} p50:{p50:.0f}ms p95:{p95:.0f}ms"
                            cv2.putText(frame, overlay_txt, (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2, cv2.LINE_AA)
                            cv2.putText(frame, overlay_txt, (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 1, cv2.LINE_AA)
                        except Exception:
                            pass
                except Exception:
                    # Keep streaming even if pose inference fails
                    pass

            # HR overlay (cached)
            try:
                if app_state is not None and hasattr(app_state, "fitbit_client"):
                    metrics = app_state.fitbit_client.get_cached_metrics()
                else:
                    metrics = None
                if metrics:
                    hr = metrics.heart_rate_bpm
                    steps = metrics.steps
                    # Zones heuristics
                    if hr < 100:
                        color = (100, 255, 100)
                        zone = "LOW"
                    elif hr < 130:
                        color = (255, 255, 0)
                        zone = "MOD"
                    elif hr < 160:
                        color = (255, 165, 0)
                        zone = "HIGH"
                    else:
                        color = (50, 50, 255)
                        zone = "VH"
                    age_s = max(0, (datetime.now(timezone.utc) - metrics.timestamp_utc).total_seconds())
                    age_txt = f"Δ{int(age_s)}s"
                    meta_txt = f"{metrics.heart_rate_source.upper()} {age_txt}"
                    hr_txt = f"HR: {hr} bpm [{zone}]"
                    box_w = 300
                    extra = 30 if steps is not None else 0
                    if metrics.error:
                        extra += 30
                    cv2.rectangle(frame, (10, 45), (10 + box_w, 45 + 60 + extra), (0, 0, 0), -1)
                    cv2.putText(frame, hr_txt, (18, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
                    cv2.putText(frame, meta_txt, (18, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
                    y = 105
                    if steps is not None:
                        steps_txt = f"Steps: {steps:,} [{metrics.steps_source.upper()}]"
                        cv2.putText(frame, steps_txt, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2, cv2.LINE_AA)
                        y += 20
                    if metrics.error:
                        err_txt = f"Err: {metrics.error}"
                        cv2.putText(frame, err_txt, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            except Exception:
                pass

            ret, buf = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            jpg = buf.tobytes()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")


@router.get("/debug/stream")
async def stream(request: Request, overlay: int = 1) -> StreamingResponse:
    return StreamingResponse(
        mjpeg_frames(overlay=bool(overlay), app_state=request.app.state),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )

        


@router.get("/debug/logs")
async def logs_tail(lines: int = 200) -> Response:
    logs_path = Path(__file__).resolve().parent.parent.parent / "data" / "logs" / "app.log"
    if not logs_path.exists():
        return PlainTextResponse("No log file yet")
    with logs_path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        # Read last ~64k or until beginning
        read_len = min(size, 64 * 1024)
        f.seek(size - read_len)
        data = f.read()
    # Return last N lines
    text = data.decode(errors="ignore").splitlines()[-lines:]
    return PlainTextResponse("\n".join(text))


@router.get("/debug/snapshot.jpg")
async def snapshot() -> Response:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    cap = pose_estimator.cap
    if cap is not None:
        ok, frame = cap.read()
        if ok:
            ret, buf = cv2.imencode('.jpg', frame)
            if ret:
                return Response(content=buf.tobytes(), media_type="image/jpeg")
    # fallback placeholder
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    ret, buf = cv2.imencode('.jpg', img)
    return Response(content=(buf.tobytes() if ret else b""), media_type="image/jpeg")


@router.get("/debug/view")
async def view() -> HTMLResponse:
    # Simple page that embeds the MJPEG stream
    html = """
        <!doctype html>
        <html>
        <head>
            <meta charset=\"utf-8\" />
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
            <title>Camera Stream</title>
            <style>
                body{margin:0;background:#111;color:#eee;font-family:sans-serif}
                .wrap{display:flex;flex-direction:column;align-items:center;gap:12px;padding:12px}
                img{max-width:100%;height:auto;border:1px solid #333}
                a{color:#8ab4f8}
                .banner{display:none;position:fixed;top:8px;left:50%;transform:translateX(-50%);padding:10px 16px;border-radius:6px;font-weight:600;z-index:1000}
                .ok{background:#1b5e20;color:#c8e6c9;border:1px solid #2e7d32}
                .info{background:#263238;color:#cfd8dc;border:1px solid #546e7a}
                .err{background:#b71c1c;color:#ffebee;border:1px solid #ef5350}
                .toolbar{display:flex;gap:12px;align-items:center}
                .btn{background:#1976d2;color:#fff;border:none;padding:8px 12px;border-radius:4px;cursor:pointer}
                .btn:hover{background:#1565c0}
            <div id="banner" class="banner info">Procesando…</div>
                .status{font-weight:600}
            </style>
        </head>
        <body>
            <div class=\"wrap\">
                <h3>Live Camera</h3>
                <div class=\"toolbar\">
                    <button class=\"btn\" onclick=\"window.location='/auth/fitbit/login'\">Connect Fitbit</button>
                    <button class=\"btn\" onclick=\"loginWithHost()\">Login with this IP</button>
                    <span class=\"status\" id=\"fitbitStatus\">Fitbit: checking…</span>
                    <a href=\"/auth/fitbit/status\" target=\"_blank\" title=\"Open status JSON\">JSON</a>
                    <a class=\"btn\" href=\"/debug/exports\" target=\"_blank\">Exports</a>
                </div>
                <small id="fitbitSample" style="color:#bbb"></small>
                <small>
                  Tip: si aparece un error de Redirect URI, use <b>Login with this IP</b> y registre esta URL exacta en el portal de Fitbit:<br/>
                  <code id=\"redirVal\"></code>
                </small>
                <img src=\"/debug/stream?overlay=1\" alt=\"stream\" />
                <p><a href=\"/debug/snapshot.jpg\" target=\"_blank\">Open snapshot</a> | <a href=\"/debug/logs\" target=\"_blank\">View logs</a> | <a href=\"/debug/stream?overlay=0\" target=\"_blank\">Raw stream</a></p>
            </div>
            <script>
                function loginWithHost(){
                    const origin = window.location.origin;
                    const redirect = origin + '/auth/fitbit/callback';
                    const url = '/auth/fitbit/login?redirect=' + encodeURIComponent(redirect);
                    window.location = url;
                }
                async function refreshStatus(){
                    try{
                        const [statusResp, metricsResp] = await Promise.all([
                            fetch('/auth/fitbit/status', {cache:'no-store'}),
                            fetch('/biometrics/last', {cache:'no-store'})
                        ]);
                        const status = await statusResp.json();
                        const metrics = await metricsResp.json();
                        const statusEl = document.getElementById('fitbitStatus');
                        if(status && status.connected){ statusEl.textContent = 'Fitbit: connected'; statusEl.style.color = '#00e676'; }
                        else { statusEl.textContent = 'Fitbit: not connected'; statusEl.style.color = '#ff5252'; }
                        const sampleEl = document.getElementById('fitbitSample');
                        if(metrics && metrics.success && metrics.data){
                            const data = metrics.data;
                            let text = `HR ${data.heart_rate_bpm} bpm (${data.heart_rate_source}) • Steps ${data.steps} (${data.steps_source})`;
                            if(data.timestamp_utc){
                                const age = Math.max(0, Math.round((Date.now() - Date.parse(data.timestamp_utc)) / 1000));
                                text += ` • Δ${age}s`;
                            }
                            if(data.error){
                                text += ` • err: ${data.error}`;
                            }
                            sampleEl.textContent = text;
                        }else{
                            sampleEl.textContent = 'Sin métricas disponibles';
                        }
                    }catch(e){
                        const statusEl = document.getElementById('fitbitStatus');
                        const sampleEl = document.getElementById('fitbitSample');
                        if(statusEl){ statusEl.textContent = 'Fitbit: error'; statusEl.style.color = '#ff5252'; }
                        if(sampleEl){ sampleEl.textContent = 'No se pudieron obtener métricas.'; }
                    }
                }
                refreshStatus();
                setInterval(refreshStatus, 5000);
                // show the exact redirect to register
                try{
                    const origin = window.location.origin;
                    const redirect = origin + '/auth/fitbit/callback';
                    const elr = document.getElementById('redirVal');
                    if(elr) elr.textContent = redirect;
                }catch(e){}
                // Banner helpers
                function showBanner(msg, kind){
                    const b = document.getElementById('banner');
                    if(!b) return;
                    b.textContent = msg;
                    b.className = 'banner ' + (kind||'info');
                    b.style.display = 'block';
                }
                // Auto-forward ?code from this view to the backend callback and show success once connected
                (function(){
                    const sp = new URLSearchParams(window.location.search);
                    if (sp.has('fitbit') && sp.get('fitbit') === 'connected'){
                        showBanner('Fitbit conectado', 'ok');
                        setTimeout(()=>{ const b=document.getElementById('banner'); if(b) b.style.display='none'; }, 3000);
                    }
                    if (sp.has('code')){
                        showBanner('Completando login de Fitbit…', 'info');
                        const code = sp.get('code');
                        const state = sp.get('state') || '';
                        const qs = new URLSearchParams({ code });
                        if(state) qs.set('state', state);
                        window.location.replace('/auth/fitbit/callback?' + qs.toString());
                    }
                })();
            </script>
        </body>
        </html>
        """
    return HTMLResponse(content=html)


@router.get("/debug/exports", response_class=HTMLResponse)
async def exports_view() -> HTMLResponse:
    root = _exports_root()
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for sub in sorted([p for p in root.iterdir() if p.is_dir()], reverse=True):
        files = [f.name for f in sub.iterdir() if f.is_file()]
        items.append({"dir": sub.name, "files": files})
    html = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Exports</title>",
        "<style>body{font-family:sans-serif;background:#111;color:#eee;padding:12px} a{color:#8ab4f8} .box{border:1px solid #333;border-radius:8px;padding:12px;margin-bottom:12px} .btn{background:#1976d2;color:#fff;border:none;padding:8px 12px;border-radius:4px;cursor:pointer} .btn:hover{background:#1565c0}</style>",
        "</head><body>",
        "<h3>Validation Exports</h3>",
        "<p><button class='btn' onclick=runExport()>Run export now</button> <small id='status'></small></p>",
        "<div id='list'>",
    ]
    for item in items:
        html.append(f"<div class='box'><b>{item['dir']}</b><ul>")
        for f in sorted(item["files"]):
            html.append(f"<li><a href='/debug/exports/file?dir={item['dir']}&name={f}' target='_blank'>{f}</a></li>")
        html.append("</ul></div>")
    html += [
        "</div>",
        "<p><a href='/reports/view' target='_blank'>Open Reports View</a> | <a href='/debug/view' target='_blank'>Back to Debug View</a></p>",
        "<script>async function runExport(){const s=document.getElementById('status');s.textContent='Running…';try{const r=await fetch('/debug/exports/run',{method:'POST'});const j=await r.json();s.textContent='Started: '+(j.dir||'');setTimeout(()=>location.reload(),1500);}catch(e){s.textContent='Error: '+e}}</script>",
        "</body></html>",
    ]
    return HTMLResponse("".join(html))


@router.get("/debug/exports/file")
async def exports_file(dir: str, name: str) -> Response:
    root = _exports_root()
    target = (root / dir / name).resolve()
    if not str(target).startswith(str(root.resolve())):
        return PlainTextResponse("Forbidden", status_code=403)
    if not target.exists() or not target.is_file():
        return PlainTextResponse("Not found", status_code=404)
    media = "text/plain"
    if name.endswith(".json"):
        media = "application/json"
    elif name.endswith(".csv"):
        media = "text/csv"
    return Response(content=target.read_bytes(), media_type=media)


@router.post("/debug/exports/run")
async def exports_run(request: Request) -> JSONResponse:
    """Trigger metrics exporter asynchronously and return the target directory name."""
    try:
        from app.metrics_exporter import generate_all_exports_async
        base_url = str(request.base_url).rstrip("/")
        # fire-and-forget; exporter will create a timestamped directory
        generate_all_exports_async(base_url=base_url)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/reports/view")
async def reports_view() -> HTMLResponse:
    """Minimal viewer for the latest export (for production Pi)."""
    root = _exports_root()
    root.mkdir(parents=True, exist_ok=True)
    latest = None
    for sub in sorted([p for p in root.iterdir() if p.is_dir()], reverse=True):
        latest = sub
        break
    summary = {}
    if latest:
        for name in ("posture_metrics.json", "biometrics_summary.json", "voice_summary.json", "performance_summary.json"):
            p = latest / name
            if p.exists():
                try:
                    summary[name] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
    html = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Resultados</title>",
        "<style>body{font-family:sans-serif;background:#111;color:#eee;padding:12px} code{background:#222;padding:2px 4px;border-radius:4px} .grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))} .box{border:1px solid #333;border-radius:8px;padding:12px}</style>",
        "</head><body>",
        "<h3>Resultados de Validación</h3>",
        f"<p>Directorio: <code>{latest.name if latest else 'N/A'}</code> <a href='/debug/exports' style='color:#8ab4f8'>Ver todos</a></p>",
        "<div class='grid'>",
    ]
    def kv(d: dict, keys: list[str]) -> str:
        return "<br/>".join([f"<b>{k}</b>: {d.get(k, '')}" for k in keys])
    pm = summary.get("posture_metrics.json") or {}
    html.append(f"<div class='box'><h4>Postura</h4>{kv(pm, ['fps','latency_ms_p50','latency_ms_p95','quality_avg'])}</div>")
    bm = summary.get("biometrics_summary.json") or {}
    html.append(f"<div class='box'><h4>Biometría</h4>{kv(bm, ['freshness_s','coverage_intraday_pct','avg_update_latency_s'])}</div>")
    vs = summary.get("voice_summary.json") or {}
    intents = list((vs.get('per_intent') or {}).keys())
    if intents:
        first = intents[0]
        vi = vs.get('per_intent', {}).get(first, {})
        html.append(f"<div class='box'><h4>Voz</h4>Intentos: {', '.join(intents)}<br/><b>{first}</b> acc: {vi.get('accuracy_pct',0)}% lat(ms): {vi.get('latency_ms',0)}</div>")
    pf = summary.get("performance_summary.json") or {}
    html.append(f"<div class='box'><h4>Desempeño</h4>{kv(pf, ['p50_total','p95_total','fps_total'])}</div>")
    html += [
        "</div>",
        "<p><small>Descargas: <a href='/debug/exports' style='color:#8ab4f8'>CSV/JSON</a></small></p>",
        "</body></html>",
    ]
    return HTMLResponse("".join(html))


@router.get("/debug/metrics")
async def metrics() -> JSONResponse:
    p50, p95 = pose_estimator.get_latency_p50_p95_ms()
    last_dt = getattr(pose_estimator, "_last_latency", 0.0)
    payload = {
        "latency_ms": {"p50": round(p50, 2), "p95": round(p95, 2)},
        "fps": {"instant": round(1.0/max(1e-6, last_dt), 2) if last_dt else 0.0, "avg": round(pose_estimator.get_fps_avg(), 2)},
        "samples": pose_estimator.get_latency_samples_count(),
    }
    return JSONResponse(content=payload)


@router.get("/debug/diag")
async def diag(request: Request) -> dict:
    s = get_settings()
    db = SessionLocal()
    try:
        tok = get_tokens(db)
        fitbit_client = getattr(request.app.state, "fitbit_client", None)
        client_diag = None
        if fitbit_client is not None:
            try:
                client_diag = fitbit_client.get_diagnostics()
            except Exception as exc:
                client_diag = {"error": str(exc)}
        camera_opened = bool(pose_estimator.cap is not None)
        pose_ready = bool(pose_estimator.pose is not None)
        lat_p50, lat_p95 = pose_estimator.get_latency_p50_p95_ms()
        fps_avg = pose_estimator.get_fps_avg()
        # Basic DNS resolution check for Fitbit API
        import socket
        dns_ok = False
        fitbit_ip = None
        try:
            fitbit_ip = socket.gethostbyname("api.fitbit.com")
            dns_ok = True if fitbit_ip else False
        except Exception:
            dns_ok = False
        return {
            "camera": {
                "opened": camera_opened,
                "index": getattr(pose_estimator, "camera_index", None),
                "width": getattr(pose_estimator, "width", None),
                "height": getattr(pose_estimator, "height", None),
                "fps_target": getattr(pose_estimator, "target_fps", None),
                "fps_avg": round(fps_avg, 2),
                "latency_ms": {
                    "p50": round(lat_p50, 2),
                    "p95": round(lat_p95, 2),
                },
                "latency_samples": pose_estimator.get_latency_samples_count(),
                "vision_mock": getattr(pose_estimator, "vision_mock", None),
                "pose_ready": pose_ready,
                "model_complexity": getattr(pose_estimator, "model_complexity", None),
            },
            "fitbit": {
                "client_id_set": bool(s.fitbit_client_id),
                "redirect_uri": s.fitbit_redirect_uri,
                "poll_interval": s.fitbit_poll_interval,
                "tokens_present": bool(tok),
                "app_state_client": bool(fitbit_client),
                "client_diagnostics": client_diag,
            },
            "network": {
                "dns_resolves_api_fitbit_com": dns_ok,
                "api_fitbit_ip": fitbit_ip,
                "note": "If false, fix DNS on the Pi (systemd-resolved/dhcpcd) and ensure Internet access."
            }
        }
    finally:
        db.close()
