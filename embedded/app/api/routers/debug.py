from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Iterator
from pathlib import Path
import time

from app.api.routers.posture import pose_estimator

router = APIRouter()


def mjpeg_frames() -> Iterator[bytes]:
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
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.1)
                continue
            ret, buf = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            jpg = buf.tobytes()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")


@router.get("/debug/stream")
async def stream() -> StreamingResponse:
    return StreamingResponse(mjpeg_frames(), media_type="multipart/x-mixed-replace; boundary=frame")


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
