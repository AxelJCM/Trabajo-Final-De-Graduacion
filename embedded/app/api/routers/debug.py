from __future__ import annotations

from fastapi import APIRouter, Response, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse
from typing import Iterator
from pathlib import Path
import time

from app.api.routers.posture import pose_estimator

router = APIRouter()


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
                    result = pose_estimator.pose.process(img_rgb)
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
                except Exception:
                    # Keep streaming even if pose inference fails
                    pass

            # HR overlay (cached)
            try:
                hr_txt = None
                if app_state is not None and hasattr(app_state, "fitbit_client"):
                    hr = app_state.fitbit_client.get_cached_hr()
                    if hr is not None:
                        # Simple zones: <100 low, 100-130 mod, 130-160 high, >160 very high (tune later by age)
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
                        hr_txt = f"HR: {hr} bpm [{zone}]"
                        cv2.rectangle(frame, (10, 45), (10 + 220, 75), (0, 0, 0), -1)
                        cv2.putText(frame, hr_txt, (18, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
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
                            .toolbar{display:flex;gap:12px;align-items:center}
                            .btn{background:#1976d2;color:#fff;border:none;padding:8px 12px;border-radius:4px;cursor:pointer}
                            .btn:hover{background:#1565c0}
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
                                </div>
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
                                    const r = await fetch('/auth/fitbit/status', {cache:'no-store'});
                                    const d = await r.json();
                                    const el = document.getElementById('fitbitStatus');
                                    if(d && d.connected){ el.textContent = 'Fitbit: connected'; el.style.color = '#00e676'; }
                                    else { el.textContent = 'Fitbit: not connected'; el.style.color = '#ff5252'; }
                                }catch(e){ /* ignore */ }
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
                        </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html)
