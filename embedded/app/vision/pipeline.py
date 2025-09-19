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

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import List

from loguru import logger

try:  # OpenCV is optional on dev machines
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

try:
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover
    mp = None  # type: ignore


@dataclass
class Joint:
    name: str
    x: float
    y: float
    score: float


@dataclass
class Angles:
    left_elbow: float
    right_elbow: float
    left_knee: float
    right_knee: float
    shoulder_hip_alignment: float


@dataclass
class PostureOutput:
    joints: List[Joint]
    angles: Angles
    feedback: str
    quality: float
    fps: float


def _angle(a, b, c) -> float:
    ax, ay = a
    bx, by = b
    cx, cy = c
    ab = (ax - bx, ay - by)
    cb = (cx - bx, cy - by)
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag_ab = math.hypot(*ab)
    mag_cb = math.hypot(*cb)
    if mag_ab == 0 or mag_cb == 0:
        return 0.0
    cosang = max(-1.0, min(1.0, dot / (mag_ab * mag_cb)))
    return math.degrees(math.acos(cosang))


class PoseEstimator:
    def __init__(self, camera_index: int | None = None):
        self.camera_index = camera_index if camera_index is not None else int(os.getenv("CAMERA_INDEX", "0"))
        self.width = int(os.getenv("CAMERA_WIDTH", "640"))
        self.height = int(os.getenv("CAMERA_HEIGHT", "480"))
        self.target_fps = int(os.getenv("CAMERA_FPS", "30"))
        self.model_complexity = int(os.getenv("MODEL_COMPLEXITY", "0"))
        self.cap = None
        self.pose = None
        self._init_video_and_model()

    def _init_video_and_model(self):
        if cv2 is not None:
            try:
                cap = cv2.VideoCapture(self.camera_index)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cap.set(cv2.CAP_PROP_FPS, self.target_fps)
                if cap.isOpened():
                    self.cap = cap
                    logger.info("Camera opened at {}x{}@{}fps (index {})", self.width, self.height, self.target_fps, self.camera_index)
            except Exception as exc:  # pragma: no cover
                logger.warning("OpenCV camera init failed: {}", exc)
        if mp is not None:
            try:
                self.pose = mp.solutions.pose.Pose(
                    static_image_mode=False,
                    model_complexity=self.model_complexity,
                    enable_segmentation=False,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("MediaPipe Pose init failed: {}", exc)

    def _mock_output(self) -> PostureOutput:
        joints = [
            Joint("left_shoulder", 0.45, 0.4, 0.9),
            Joint("right_shoulder", 0.55, 0.4, 0.9),
            Joint("left_elbow", 0.42, 0.55, 0.85),
            Joint("right_elbow", 0.58, 0.55, 0.85),
            Joint("left_hip", 0.48, 0.65, 0.85),
            Joint("right_hip", 0.52, 0.65, 0.85),
            Joint("left_knee", 0.48, 0.82, 0.8),
            Joint("right_knee", 0.52, 0.82, 0.8),
        ]
        angles = Angles(160.0, 160.0, 170.0, 170.0, 0.0)
        return PostureOutput(joints=joints, angles=angles, feedback="Postura OK", quality=87.0, fps=0.0)

    def _compute_output(self, landmarks_norm, fps: float) -> PostureOutput:
        lm = {name: (landmarks_norm[name][0], landmarks_norm[name][1]) for name in landmarks_norm}
        ang_left_elbow = _angle(lm["LEFT_SHOULDER"], lm["LEFT_ELBOW"], lm["LEFT_WRIST"]) if all(k in lm for k in ["LEFT_SHOULDER","LEFT_ELBOW","LEFT_WRIST"]) else 0.0
        ang_right_elbow = _angle(lm["RIGHT_SHOULDER"], lm["RIGHT_ELBOW"], lm["RIGHT_WRIST"]) if all(k in lm for k in ["RIGHT_SHOULDER","RIGHT_ELBOW","RIGHT_WRIST"]) else 0.0
        ang_left_knee = _angle(lm["LEFT_HIP"], lm["LEFT_KNEE"], lm["LEFT_ANKLE"]) if all(k in lm for k in ["LEFT_HIP","LEFT_KNEE","LEFT_ANKLE"]) else 0.0
        ang_right_knee = _angle(lm["RIGHT_HIP"], lm["RIGHT_KNEE"], lm["RIGHT_ANKLE"]) if all(k in lm for k in ["RIGHT_HIP","RIGHT_KNEE","RIGHT_ANKLE"]) else 0.0
        align = (lm.get("LEFT_SHOULDER", (0, 0))[1] + lm.get("RIGHT_SHOULDER", (0, 0))[1]) / 2 - (
            (lm.get("LEFT_HIP", (0, 0))[1] + lm.get("RIGHT_HIP", (0, 0))[1]) / 2
        )
        shoulder_hip_alignment = abs(align)

        joints = [
            Joint("left_shoulder", *lm.get("LEFT_SHOULDER", (0.0, 0.0)), 0.9),
            Joint("right_shoulder", *lm.get("RIGHT_SHOULDER", (0.0, 0.0)), 0.9),
            Joint("left_elbow", *lm.get("LEFT_ELBOW", (0.0, 0.0)), 0.8),
            Joint("right_elbow", *lm.get("RIGHT_ELBOW", (0.0, 0.0)), 0.8),
            Joint("left_hip", *lm.get("LEFT_HIP", (0.0, 0.0)), 0.8),
            Joint("right_hip", *lm.get("RIGHT_HIP", (0.0, 0.0)), 0.8),
            Joint("left_knee", *lm.get("LEFT_KNEE", (0.0, 0.0)), 0.75),
            Joint("right_knee", *lm.get("RIGHT_KNEE", (0.0, 0.0)), 0.75),
        ]
        angles = Angles(
            left_elbow=ang_left_elbow,
            right_elbow=ang_right_elbow,
            left_knee=ang_left_knee,
            right_knee=ang_right_knee,
            shoulder_hip_alignment=shoulder_hip_alignment,
        )

        quality = 100.0
        if shoulder_hip_alignment > 0.05:
            quality -= min(40.0, shoulder_hip_alignment * 400)
        for a in [ang_left_elbow, ang_right_elbow, ang_left_knee, ang_right_knee]:
            if a == 0.0:
                quality -= 10.0

        feedback = "Postura OK" if quality >= 80 else ("Atención a la alineación" if quality >= 60 else "Corrige postura")

        return PostureOutput(joints=joints, angles=angles, feedback=feedback, quality=max(0.0, min(100.0, quality)), fps=fps)

    def analyze_frame(self) -> PostureOutput:
        # If no camera or mediapipe, return mock
        if self.cap is None or self.pose is None:
            return self._mock_output()

        t0 = time.time()
        ok, frame = self.cap.read()
        if not ok:
            return self._mock_output()
        img = frame
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        result = self.pose.process(img_rgb)
        fps = 1.0 / max(1e-6, (time.time() - t0))

        if not result.pose_landmarks:
            out = self._mock_output()
            out.fps = fps
            return out

        # Normalize landmarks to [0,1] using image size
        h, w = img.shape[:2]
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
        landmarks_norm = {}
        for idx, lm in enumerate(result.pose_landmarks.landmark):
            if idx in idx_to_name:
                landmarks_norm[idx_to_name[idx]] = (lm.x, lm.y)

        out = self._compute_output(landmarks_norm, fps=fps)

        # Graceful degradation if fps too low
        if fps < 10.0:
            if self.width > 640 or self.height > 360:
                self.width = 640
                self.height = 360
                logger.info("Low FPS detected ({:.1f}). Reducing resolution to {}x{}.", fps, self.width, self.height)
                try:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                except Exception:
                    pass
            if self.model_complexity != 0 and mp is not None:
                logger.info("Setting model_complexity to 0 for performance")
                try:
                    self.pose.close()
                except Exception:
                    pass
                self.model_complexity = 0
                try:
                    self.pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=0, enable_segmentation=False, min_detection_confidence=0.5, min_tracking_confidence=0.5)
                except Exception:
                    pass

        return out

    def snapshot(self) -> PostureOutput:
        # Use analyze_frame; if no hardware it returns mock
        out = self.analyze_frame()
        return out
