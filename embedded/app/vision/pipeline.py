"""Vision pipeline for posture analysis using OpenCV and MediaPipe.

Exposes PoseEstimator.analyze_frame() returning PostureOutput.
"""
from __future__ import annotations

import time
from typing import List

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - allow tests w/o OpenCV
    cv2 = None  # type: ignore

from loguru import logger

from app.api.schemas import PostureOutput, Joint


class PoseEstimator:
    """Simple pose estimator wrapper.

    In production, initialize camera and MediaPipe pose graph. For now, returns
    placeholder joints and computed FPS.
    """

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self._last_time = time.perf_counter()

    def _dummy_joints(self) -> List[Joint]:
        return [
            Joint(name="nose", x=0.5, y=0.2, score=0.9),
            Joint(name="left_shoulder", x=0.4, y=0.4, score=0.95),
            Joint(name="right_shoulder", x=0.6, y=0.4, score=0.95),
        ]

    def analyze_frame(self) -> PostureOutput:
        now = time.perf_counter()
        dt = max(now - self._last_time, 1e-3)
        self._last_time = now
        fps = 1.0 / dt
        logger.debug("vision fps={}", fps)
        joints = self._dummy_joints()
        # Simple heuristic: shoulder alignment
        ls = next((j for j in joints if j.name == "left_shoulder"), None)
        rs = next((j for j in joints if j.name == "right_shoulder"), None)
        feedback = "Postura OK"
        if ls and rs and abs(ls.y - rs.y) > 0.05:
            feedback = "Ajusta los hombros al mismo nivel"
        return PostureOutput(fps=fps, joints=joints, feedback=feedback)

    def snapshot(self) -> PostureOutput:
        """Return a posture analysis snapshot that works without a camera.

        Falls back to deterministic joints (mock) and fps≈0 when camera/images are unavailable.
        """
        try:
            # Placeholder: if cv2 and a sample image exist, load and analyze; else mock
            sample_path = __file__.replace("pipeline.py", "../../assets/sample_pose.jpg")
            # Not actually used yet—kept for future extension
        except Exception:
            pass
        out = self.analyze_frame()
        # Force fps ~0 for snapshot semantics
        out.fps = 0.0
        return out
