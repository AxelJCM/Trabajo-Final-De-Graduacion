from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Iterator
from pathlib import Path
import time

from app.vision.pipeline import PoseEstimator

router = APIRouter()

pose_estimator = PoseEstimator()


def mjpeg_frames() -> Iterator[bytes]:
    cap = pose_estimator.cap
    import cv2  # type: ignore
    if cap is None:
        # empty stream when no camera
        while True:
            time.sleep(0.5)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + b"" + b"\r\n")
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
