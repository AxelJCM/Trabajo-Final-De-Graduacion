"""Pose estimation pipeline with rep counting, quality metrics, and HUD payload."""
from __future__ import annotations

import math
import time
from collections import deque
import base64
from dataclasses import dataclass, asdict, field
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from loguru import logger

try:  # Optional dependencies when running on the Raspberry Pi
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

try:  # Optional when running in CI
    import mediapipe as mp  # type: ignore
except Exception:  # pragma: no cover
    mp = None  # type: ignore

from app.core.config import get_settings


@dataclass
class PoseJoint:
    name: str
    x: float
    y: float
    z: float
    score: float


@dataclass
class PoseAngles:
    left_elbow: Optional[float] = None
    right_elbow: Optional[float] = None
    left_knee: Optional[float] = None
    right_knee: Optional[float] = None
    left_hip: Optional[float] = None
    right_hip: Optional[float] = None
    shoulder_hip_alignment: Optional[float] = None
    torso_forward: Optional[float] = None


@dataclass
class PoseResult:
    fps: float
    latency_ms: float
    latency_ms_p50: float
    latency_ms_p95: float
    joints: List[PoseJoint]
    angles: PoseAngles
    quality: float
    quality_avg: float
    feedback: str
    feedback_code: str
    exercise: str
    phase: str
    phase_label: str
    rep_count: int
    current_exercise_reps: int
    rep_totals: Dict[str, int] = field(default_factory=dict)
    timestamp_utc: float = field(default_factory=lambda: time.time())
    frame_b64: Optional[str] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["joints"] = [asdict(j) for j in self.joints]
        result["angles"] = asdict(self.angles)
        return result


class PoseEstimator:
    """Pose estimation pipeline with MediaPipe fallback to mock data."""

    _SPANISH_PHASE = {"up": "Ascenso", "down": "Descenso"}

    def __init__(self) -> None:
        self.settings = get_settings()
        # Nota: mantener en minúsculas internamente; el HUD lo muestra con mayúscula inicial
        self.exercise: str = "squat"
        self.phase: str = "up"
        self.rep_count: int = 0
        self.rep_totals: Dict[str, int] = {"squat": 0, "pushup": 0, "crunch": 0}
        self.feedback: str = "Listo para empezar"
        self.feedback_code: str = "idle"
        self.counting_enabled: bool = False
        self._latencies: deque[float] = deque(maxlen=max(5, self.settings.pose_latency_window))
        self._quality_window: deque[float] = deque(maxlen=max(5, self.settings.pose_quality_window))
        self._quality_sum: float = 0.0
        self._quality_count: int = 0
        self._fps_window: deque[float] = deque(maxlen=60)
        self._last_frame_ts: Optional[float] = None
        self._mock: bool = bool(self.settings.vision_mock or cv2 is None or mp is None)
        self._pose = None
        self._cap = None
        self._mp_landmarks = None
        self._mock_progress: float = 0.0
        self._frame_counter: int = 0
        self._last_joints: List[PoseJoint] = []
        self._last_angles: PoseAngles = PoseAngles()
        # Front-facing robustness: smooth primary angle and require confirmation frames
        self._angle_window: deque[float] = deque(maxlen=5)
        self._phase_condition_frames: int = 0
        self._thresholds = {
            "squat": {
                "down": float(self.settings.squat_down_angle),
                "up": float(self.settings.squat_up_angle),
            },
            "pushup": {
                "down": float(self.settings.pushup_down_angle),
                "up": float(self.settings.pushup_up_angle),
            },
            "crunch": {
                "down": float(self.settings.crunch_down_angle),
                "up": float(self.settings.crunch_up_angle),
            },
        }

        if not self._mock:
            try:
                self._init_realtime_pipeline()
            except Exception as exc:  # pragma: no cover
                logger.warning("Falling back to pose mock pipeline: {}", exc)
                self._mock = True

        if self._mock:
            logger.info("PoseEstimator running in mock mode (VISION_MOCK=1 or missing deps)")

    # --- Public API -----------------------------------------------------

    def analyze_frame(self) -> PoseResult:
        """Capture a frame, compute joints/angles, rep counting, and metrics."""
        start = time.perf_counter()
        joints, angles, frame = self._process_frame()
        latency_ms = (time.perf_counter() - start) * 1000.0
        self._latencies.append(latency_ms)
        fps = self._update_fps()
        latency_p50, latency_p95 = self._latency_percentiles()

        # Gate quality and rep counting by session activity (counting_enabled)
        # - When not active/paused, don't count reps and don't accumulate quality metrics.
        if self.counting_enabled:
            quality = self._compute_quality(angles)
            self._quality_window.append(quality)
            self._quality_sum += quality
            self._quality_count += 1
            avg_quality = self.get_average_quality()
            self._update_reps(angles)
            feedback_code, feedback = self._feedback_for_angles(angles, quality)
        else:
            quality = 0.0
            # Do not change accumulated average while inactive/paused
            avg_quality = self.get_average_quality()
            # Still update phase transitions internally but do not increment reps
            self._update_reps(angles)
            feedback_code, feedback = "idle", "Listo para empezar"

        self.feedback_code = feedback_code
        self.feedback = feedback

        frame_b64 = self._encode_frame(frame, joints, quality, angles)

        result = PoseResult(
            fps=round(fps, 2),
            latency_ms=round(latency_ms, 2),
            latency_ms_p50=round(latency_p50, 2),
            latency_ms_p95=round(latency_p95, 2),
            joints=joints,
            angles=angles,
            quality=round(quality, 2),
            quality_avg=round(avg_quality, 2),
            feedback=feedback,
            feedback_code=feedback_code,
            exercise=self.exercise,
            phase=self.phase,
            phase_label=self._SPANISH_PHASE.get(self.phase, self.phase.title()),
            rep_count=self.rep_count,
            current_exercise_reps=self.rep_totals.get(self.exercise, 0),
            rep_totals=dict(self.rep_totals),
            frame_b64=frame_b64,
        )
        return result

    def get_average_quality(self) -> float:
        if not self._quality_count:
            return 0.0
        return self._quality_sum / self._quality_count

    def get_fps_avg(self) -> float:
        if not self._fps_window:
            return 0.0
        return sum(self._fps_window) / len(self._fps_window)

    def get_latency_samples_count(self) -> int:
        return len(self._latencies)

    def get_latency_p50_p95_ms(self) -> Tuple[float, float]:
        """Return latency percentiles in milliseconds."""
        return self._latency_percentiles()

    def reset_session(self, exercise: Optional[str] = None, *, preserve_totals: bool = False) -> None:
        if exercise:
            self.exercise = exercise.lower()
        self.phase = "up"
        self.rep_count = 0
        if preserve_totals:
            self.rep_totals.setdefault(self.exercise, 0)
        else:
            self.rep_totals = {k: 0 for k in self.rep_totals}
            self.rep_totals.setdefault(self.exercise, 0)
        self.feedback = "Listo para empezar"
        self.feedback_code = "idle"
        self._latencies.clear()
        self._quality_window.clear()
        self._quality_sum = 0.0
        self._quality_count = 0
        self._fps_window.clear()
        self._last_frame_ts = None
        self._mock_progress = 0.0
        self.counting_enabled = False

    def set_exercise(self, exercise: str, *, reset: bool = False) -> None:
        exercise_name = exercise.lower()
        if reset:
            was_enabled = self.counting_enabled
            self.reset_session(exercise=exercise_name, preserve_totals=False)
            self.counting_enabled = was_enabled
            return
        self.exercise = exercise_name
        self.phase = "up"
        self.rep_totals.setdefault(self.exercise, 0)
        self.feedback = "Ejercicio actualizado"
        self.feedback_code = "exercise_changed"

    def set_counting_enabled(self, enabled: bool) -> None:
        self.counting_enabled = bool(enabled)

    def get_phase_label(self) -> str:
        return self._SPANISH_PHASE.get(self.phase, self.phase.title())

    # --- Debug accessors (used by /debug endpoints) --------------------
    @property
    def cap(self):  # pragma: no cover - debug tooling
        return self._cap

    @property
    def pose(self):  # pragma: no cover - debug tooling
        return self._pose

    # --- Internal helpers -----------------------------------------------

    def _init_realtime_pipeline(self) -> None:  # pragma: no cover - hardware path
        assert cv2 is not None and mp is not None
        try:
            # Limit OpenCV threads on low-power devices (reduces contention)
            if hasattr(cv2, "setNumThreads"):
                cv2.setNumThreads(int(self.settings.opencv_threads))
        except Exception:
            pass
        mp_pose = mp.solutions.pose
        self._pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=int(self.settings.model_complexity),
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._mp_landmarks = mp_pose.PoseLandmark
        self._cap = cv2.VideoCapture(int(self.settings.camera_index))
        if not self._cap or not self._cap.isOpened():
            raise RuntimeError("Camera could not be opened")
        self._configure_camera()

    def _configure_camera(self) -> None:  # pragma: no cover - hardware path
        assert cv2 is not None and self._cap is not None
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.settings.camera_width))
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.settings.camera_height))
        self._cap.set(cv2.CAP_PROP_FPS, int(self.settings.camera_fps))
        # Reduce camera internal buffer to minimize latency
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        # Optionally force a specific FOURCC (e.g., MJPG) for higher FPS on USB webcams
        try:
            fourcc = (self.settings.camera_fourcc or "").strip().upper()
            if fourcc:
                code = cv2.VideoWriter_fourcc(*fourcc[:4])
                self._cap.set(cv2.CAP_PROP_FOURCC, code)
        except Exception:
            pass

    def _process_frame(self) -> Tuple[List[PoseJoint], PoseAngles, Optional[np.ndarray]]:
        if self._mock:
            return self._mock_frame()
        assert self._cap is not None and cv2 is not None and mp is not None
        ok, frame = self._cap.read()
        if not ok:
            logger.warning("Camera read failed; switching to mock mode")
            self._mock = True
            return self._mock_frame()
        # Frame skipping: process only 1 of (skip+1) frames, reuse last angles/joints otherwise
        self._frame_counter += 1
        do_process = True
        skip = max(0, int(getattr(self.settings, "pose_frame_skip", 0)))
        if skip > 0 and (self._frame_counter % (skip + 1) != 0) and self._last_joints and self._last_angles:
            do_process = False

        results = None
        if do_process:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Optional downscale for inference to speed up MediaPipe
            target_long = max(0, int(getattr(self.settings, "pose_input_long_side", 0)))
            if target_long and max(rgb.shape[0], rgb.shape[1]) > target_long:
                h, w = rgb.shape[:2]
                scale = float(target_long) / float(max(h, w))
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                rgb_small = cv2.resize(rgb, new_size, interpolation=cv2.INTER_AREA)
                results = self._pose.process(rgb_small) if self._pose else None  # type: ignore[attr-defined]
            else:
                results = self._pose.process(rgb) if self._pose else None  # type: ignore[attr-defined]
        if not results or not results.pose_landmarks:
            if do_process:
                # No detection; reset last values
                self._last_joints = []
                self._last_angles = PoseAngles()
            # Return previous if available to keep FPS high; else empty
            return list(self._last_joints), self._last_angles, frame
        landmarks = results.pose_landmarks.landmark
        points = self._landmark_points(landmarks)
        joints = [
            PoseJoint(name=name, x=pt[0], y=pt[1], z=pt[2], score=pt[3])
            for name, pt in points.items()
        ]
        angles = self._compute_angles(points)
        # Cache for skipped frames
        self._last_joints = list(joints)
        self._last_angles = angles
        return joints, angles, frame

    def _landmark_points(self, landmarks) -> Dict[str, Tuple[float, float, float, float]]:
        if mp is None:
            return {}
        lm = self._mp_landmarks
        indices = {
            "left_shoulder": lm.LEFT_SHOULDER,
            "right_shoulder": lm.RIGHT_SHOULDER,
            "left_elbow": lm.LEFT_ELBOW,
            "right_elbow": lm.RIGHT_ELBOW,
            "left_wrist": lm.LEFT_WRIST,
            "right_wrist": lm.RIGHT_WRIST,
            "left_hip": lm.LEFT_HIP,
            "right_hip": lm.RIGHT_HIP,
            "left_knee": lm.LEFT_KNEE,
            "right_knee": lm.RIGHT_KNEE,
            "left_ankle": lm.LEFT_ANKLE,
            "right_ankle": lm.RIGHT_ANKLE,
            "nose": lm.NOSE,
        }
        points: Dict[str, Tuple[float, float, float, float]] = {}
        for name, idx in indices.items():
            landmark = landmarks[int(idx)]
            points[name] = (
                float(landmark.x),
                float(landmark.y),
                float(landmark.z),
                float(getattr(landmark, "visibility", 1.0)),
            )
        return points

    def _compute_angles(self, points: Dict[str, Tuple[float, float, float, float]]) -> PoseAngles:
        def get(names: Iterable[str]) -> Optional[Tuple[float, float, float]]:
            coords = []
            for n in names:
                if n not in points:
                    return None
                coords.append(points[n][:3])
            return tuple(coords)  # type: ignore[return-value]

        def angle(a: Tuple[float, float, float], b: Tuple[float, float, float], c: Tuple[float, float, float]) -> float:
            v1 = np.array(a) - np.array(b)
            v2 = np.array(c) - np.array(b)
            norm = np.linalg.norm(v1) * np.linalg.norm(v2)
            if norm == 0:
                return 0.0
            cos = np.clip(np.dot(v1, v2) / norm, -1.0, 1.0)
            return math.degrees(math.acos(cos))

        left_elbow = angle(*get(("left_shoulder", "left_elbow", "left_wrist"))) if get(("left_shoulder", "left_elbow", "left_wrist")) else None
        right_elbow = angle(*get(("right_shoulder", "right_elbow", "right_wrist"))) if get(("right_shoulder", "right_elbow", "right_wrist")) else None
        left_knee = angle(*get(("left_hip", "left_knee", "left_ankle"))) if get(("left_hip", "left_knee", "left_ankle")) else None
        right_knee = angle(*get(("right_hip", "right_knee", "right_ankle"))) if get(("right_hip", "right_knee", "right_ankle")) else None
        left_hip = angle(*get(("left_shoulder", "left_hip", "left_knee"))) if get(("left_shoulder", "left_hip", "left_knee")) else None
        right_hip = angle(*get(("right_shoulder", "right_hip", "right_knee"))) if get(("right_shoulder", "right_hip", "right_knee")) else None
        shoulder_hip = angle(*get(("left_shoulder", "left_hip", "right_hip"))) if get(("left_shoulder", "left_hip", "right_hip")) else None

        torso_angle: Optional[float] = None
        if all(n in points for n in ("left_shoulder", "left_hip", "right_hip")):
            shoulder = np.array(points["left_shoulder"][:3])
            hip_mid = (
                np.array(points["left_hip"][:3]) + np.array(points["right_hip"][:3])
            ) / 2.0
            vec = shoulder - hip_mid
            torso_angle = math.degrees(math.atan2(abs(vec[0]), abs(vec[1]) + 1e-6))

        return PoseAngles(
            left_elbow=left_elbow,
            right_elbow=right_elbow,
            left_knee=left_knee,
            right_knee=right_knee,
            left_hip=left_hip,
            right_hip=right_hip,
            shoulder_hip_alignment=shoulder_hip,
            torso_forward=torso_angle,
        )

    def _update_fps(self) -> float:
        now = time.perf_counter()
        if self._last_frame_ts is None:
            self._last_frame_ts = now
            return float(self.settings.camera_fps or 0)
        delta = now - self._last_frame_ts
        self._last_frame_ts = now
        if delta <= 0:
            return float(self.settings.camera_fps or 0)
        fps = 1.0 / delta
        self._fps_window.append(fps)
        return sum(self._fps_window) / len(self._fps_window)

    def _latency_percentiles(self) -> Tuple[float, float]:
        if not self._latencies:
            return 0.0, 0.0
        data = list(self._latencies)
        try:
            p50 = float(np.percentile(data, 50))
            p95 = float(np.percentile(data, 95))
        except Exception:
            p50 = float(median(data))
            p95 = float(sorted(data)[max(0, int(len(data) * 95 / 100) - 1)])
        return p50, p95

    def _compute_quality(self, angles: PoseAngles) -> float:
        thresholds = self._thresholds.get(self.exercise, self._thresholds["squat"])
        down = thresholds["down"]
        up = thresholds["up"]
        # Quality compares against expected posture for current phase
        target = up if self.phase == "up" else down
        angle_value = self._primary_angle_smoothed(angles)
        if angle_value is None:
            return 0.0
        error = abs(angle_value - target)
        # Normalize error by the angular range and clamp
        range_span = max(10.0, abs(up - down))
        score = max(0.0, 100.0 - (error / range_span) * 120.0)
        return max(0.0, min(100.0, score))

    def _primary_angle(self, angles: PoseAngles) -> Optional[float]:
        if self.exercise == "squat":
            candidates = [v for v in (angles.left_knee, angles.right_knee) if v is not None]
        elif self.exercise == "pushup":
            # Front-facing robustness: for pushups, prefer the minimum elbow angle (the arm that bends more)
            # instead of averaging both. This makes transitions easier to detect even with partial occlusions.
            elbows = [v for v in (angles.left_elbow, angles.right_elbow) if v is not None]
            if elbows:
                # Use min to reflect the deepest flexion
                return float(min(elbows))
            candidates = []
        else:  # crunch (front-facing): prefer hip angles; fallback to shoulder-hip alignment
            hip_candidates = [v for v in (angles.left_hip, angles.right_hip) if v is not None]
            if hip_candidates:
                candidates = hip_candidates
            else:
                candidates = [v for v in (angles.shoulder_hip_alignment,) if v is not None]
        if not candidates:
            return None
        return float(sum(candidates) / len(candidates))

    def _primary_angle_smoothed(self, angles: PoseAngles) -> Optional[float]:
        val = self._primary_angle(angles)
        if val is None:
            return None
        self._angle_window.append(float(val))
        return float(sum(self._angle_window) / max(1, len(self._angle_window)))

    def _update_reps(self, angles: PoseAngles) -> None:
        angle_value = self._primary_angle_smoothed(angles)
        if angle_value is None:
            return
        thresholds = self._thresholds.get(self.exercise, self._thresholds["squat"])
        down = thresholds["down"]
        up = thresholds["up"]
        hyster = float(getattr(self.settings, "pose_rep_hysteresis_deg", 8.0))
        need_frames = max(1, int(getattr(self.settings, "pose_rep_confirm_frames", 2)))
        if self.phase == "up":
            condition = angle_value <= (down + hyster)
            if condition:
                self._phase_condition_frames += 1
                if self._phase_condition_frames >= need_frames:
                    self.phase = "down"
                    self._phase_condition_frames = 0
            else:
                self._phase_condition_frames = 0
        else:  # phase == 'down'
            condition = angle_value >= (up - hyster)
            if condition:
                self._phase_condition_frames += 1
                if self._phase_condition_frames >= need_frames:
                    self.phase = "up"
                    self._phase_condition_frames = 0
                    if self.counting_enabled:
                        self.rep_count += 1
                        self.rep_totals[self.exercise] = self.rep_totals.get(self.exercise, 0) + 1
            else:
                self._phase_condition_frames = 0

    def _feedback_for_angles(self, angles: PoseAngles, quality: float) -> Tuple[str, str]:
        angle_value = self._primary_angle_smoothed(angles)
        if angle_value is None:
            return "no_skeleton", "No se detecta el cuerpo"

        thresholds = self._thresholds.get(self.exercise, self._thresholds["squat"])
        down = thresholds["down"]
        up = thresholds["up"]
        margin = max(5.0, (up - down) * 0.1)

        # Part-aware feedback: choose the most problematic part and craft the message
        parts = self._compute_part_colors(angles)
        def worst(parts_map: Dict[str, str], order: list[str]) -> Optional[str]:
            # Priority: torso > left/right part
            for severity in ("red", "yellow"):
                for key in order:
                    if parts_map.get(key) == severity:
                        return key
            return None
        # Heuristics per exercise
        if self.exercise == "squat":
            target = up if self.phase == "up" else down
            key = worst(parts, ["torso", "left_leg", "right_leg"])
            if key == "torso":
                return "straight_back", "Mantén la espalda recta"
            if key in ("left_leg", "right_leg"):
                side = "izquierda" if key == "left_leg" else "derecha"
                if angle_value > target:  # le falta flexión al bajar
                    return "go_lower_" + side, f"Baja más con la rodilla {side}"
                else:
                    return "extend_" + side, f"Extiende más la rodilla {side}"
        elif self.exercise == "pushup":
            target = up if self.phase == "up" else down
            key = worst(parts, ["left_arm", "right_arm", "torso"])
            if key in ("left_arm", "right_arm"):
                side = "izquierdo" if key == "left_arm" else "derecho"
                if angle_value > target:
                    return "go_lower_" + side, f"Flexiona más el codo {side}"
                else:
                    return "extend_" + side, f"Extiende más el codo {side}"
            if key == "torso":
                return "brace_core", "Activa el core; evita arquear el torso"
        elif self.exercise == "crunch":
            target = up if self.phase == "up" else down
            key = worst(parts, ["torso", "left_leg", "right_leg"])  # torso refleja flexión del tronco
            if key == "torso":
                if angle_value < target - margin:
                    return "protect_neck", "No cargues el cuello"
                return "go_higher", "Activa el abdomen y sube"

        # Fallback genérico si no se detecta parte dominante
        if self.exercise == "squat":
            if angle_value > up - margin:
                return "go_lower", "Baja más la cadera"
            if angle_value < down + margin:
                return "control_up", "Controla el ascenso"
        elif self.exercise == "pushup":
            if angle_value > up - margin:
                return "go_lower", "Flexiona más los codos"
            if angle_value < down + margin:
                return "control_up", "Sube con control"
        elif self.exercise == "crunch":
            if angle_value < down - margin:
                return "protect_neck", "No cargues el cuello"
            if angle_value > up - margin:
                return "go_higher", "Activa el abdomen y sube"

        if quality >= 85:
            return "excellent", "Excelente técnica"
        if quality >= 65:
            return "good", "Buen ritmo"
        return "keep_trying", "Sigue así, estabiliza el movimiento"

    def _mock_frame(self) -> Tuple[List[PoseJoint], PoseAngles, Optional[np.ndarray]]:
        self._mock_progress = (self._mock_progress + 0.12) % (2 * math.pi)
        depth = (math.sin(self._mock_progress) + 1) / 2  # 0..1
        thresholds = self._thresholds.get(self.exercise, self._thresholds["squat"])
        up = thresholds["up"]
        down = thresholds["down"]
        angle_value = up - (up - down) * depth

        left_elbow = right_elbow = 165.0
        left_knee = right_knee = 160.0
        left_hip = right_hip = 150.0
        torso_forward = 12.0
        shoulder_alignment = 150.0

        if self.exercise == "squat":
            left_knee = angle_value
            right_knee = angle_value
            torso_forward = 10.0 + depth * 10.0
        elif self.exercise == "pushup":
            left_elbow = angle_value
            right_elbow = angle_value
            left_knee = right_knee = 175.0
            torso_forward = 5.0
        else:  # crunch
            left_hip = angle_value
            right_hip = angle_value
            left_knee = right_knee = 90.0
            left_elbow = right_elbow = 160.0
            torso_forward = 15.0 + depth * 8.0
            shoulder_alignment = 140.0 - depth * 25.0

        joints = [
            PoseJoint("left_shoulder", 0.45, 0.35, -0.1, 0.9),
            PoseJoint("right_shoulder", 0.55, 0.35, -0.1, 0.9),
            PoseJoint("left_hip", 0.47, 0.55, -0.1, 0.9),
            PoseJoint("right_hip", 0.53, 0.55, -0.1, 0.9),
            PoseJoint("left_knee", 0.47, 0.75, -0.1, 0.9),
            PoseJoint("right_knee", 0.53, 0.75, -0.1, 0.9),
            PoseJoint("left_elbow", 0.42, 0.45, -0.1, 0.9),
            PoseJoint("right_elbow", 0.58, 0.45, -0.1, 0.9),
            PoseJoint("left_wrist", 0.40, 0.52, -0.1, 0.9),
            PoseJoint("right_wrist", 0.60, 0.52, -0.1, 0.9),
            PoseJoint("left_ankle", 0.47, 0.92, -0.1, 0.9),
            PoseJoint("right_ankle", 0.53, 0.92, -0.1, 0.9),
        ]

        angles = PoseAngles(
            left_elbow=left_elbow,
            right_elbow=right_elbow,
            left_knee=left_knee,
            right_knee=right_knee,
            left_hip=left_hip,
            right_hip=right_hip,
            shoulder_hip_alignment=shoulder_alignment,
            torso_forward=torso_forward,
        )
        frame = self._generate_mock_frame(angle_value, depth)
        return joints, angles, frame

    def _generate_mock_frame(self, angle_value: float, depth: float) -> Optional[np.ndarray]:
        if cv2 is None:
            return None
        height, width = 1280, 720
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        gradient = int(60 + depth * 140)
        frame[:, :] = (25, 25 + gradient, 40 + gradient)
        center_x = width // 2
        center_y = int(height * (0.35 + 0.25 * math.sin(self._mock_progress)))
        cv2.circle(frame, (center_x, center_y), 80, (255, 255, 255), -1)
        cv2.putText(
            frame,
            f"{self.exercise.upper()} {int(angle_value)}",
            (40, height - 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return frame

    def _apply_rotation(self, frame: np.ndarray, angle: int) -> np.ndarray:
        if cv2 is None:
            return frame
        normalized = angle % 360
        if normalized == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if normalized == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if normalized == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _draw_skeleton(self, frame: np.ndarray, joints: List[PoseJoint], quality: float, angles: PoseAngles) -> np.ndarray:
        if cv2 is None or not joints:
            return frame
        height, width = frame.shape[:2]
        joint_map = {j.name: j for j in joints}
        # Compute per-part status colors (green/yellow/red) based on angle deviations
        part_colors = self._compute_part_colors(angles)
        def color_for(part: str) -> tuple[int, int, int]:
            level = part_colors.get(part, "green")
            if level == "red":
                return (0, 0, 255)
            if level == "yellow":
                return (0, 215, 255)
            return (0, 200, 0)
        thickness = max(2, width // 240)
        radius = max(3, width // 180)
        # Map each connection to a part for coloring
        connections = [
            ("left_ankle", "left_knee", "left_leg"),
            ("left_knee", "left_hip", "left_leg"),
            ("left_hip", "left_shoulder", "torso"),
            ("left_shoulder", "left_elbow", "left_arm"),
            ("left_elbow", "left_wrist", "left_arm"),
            ("right_ankle", "right_knee", "right_leg"),
            ("right_knee", "right_hip", "right_leg"),
            ("right_hip", "right_shoulder", "torso"),
            ("right_shoulder", "right_elbow", "right_arm"),
            ("right_elbow", "right_wrist", "right_arm"),
            ("left_shoulder", "right_shoulder", "torso"),
            ("left_hip", "right_hip", "torso"),
        ]

        def to_pixel(j: PoseJoint) -> Tuple[int, int]:
            return int(j.x * width), int(j.y * height)

        for a, b, part in connections:
            ja = joint_map.get(a)
            jb = joint_map.get(b)
            if ja and jb and ja.score > 0.2 and jb.score > 0.2:
                cv2.line(frame, to_pixel(ja), to_pixel(jb), color_for(part), thickness, cv2.LINE_AA)
        for joint in joints:
            if joint.score <= 0.2:
                continue
            # Color joint by its closest part
            if joint.name.startswith("left_") and any(x in joint.name for x in ("knee","ankle","hip")):
                jc = color_for("left_leg")
            elif joint.name.startswith("right_") and any(x in joint.name for x in ("knee","ankle","hip")):
                jc = color_for("right_leg")
            elif joint.name.startswith("left_") and any(x in joint.name for x in ("elbow","wrist","shoulder")):
                jc = color_for("left_arm")
            elif joint.name.startswith("right_") and any(x in joint.name for x in ("elbow","wrist","shoulder")):
                jc = color_for("right_arm")
            else:
                jc = color_for("torso")
            cv2.circle(frame, to_pixel(joint), radius, jc, thickness=-1, lineType=cv2.LINE_AA)
        return frame

    def _encode_frame(self, frame: Optional[np.ndarray], joints: List[PoseJoint], quality: float, angles: PoseAngles) -> Optional[str]:
        if frame is None or cv2 is None:
            return None
        if getattr(self.settings, "hud_disable", False):
            return None
        frame_to_encode = frame.copy()
        frame_to_encode = self._draw_skeleton(frame_to_encode, joints, quality, angles)
        rotate = int(getattr(self.settings, "hud_frame_rotate", 0))
        frame_to_encode = self._apply_rotation(frame_to_encode, rotate)
        h, w = frame_to_encode.shape[:2]
        target_long_side = int(getattr(self.settings, "hud_target_long_side", 960))
        scale = target_long_side / float(max(h, w))
        if scale < 1.0:
            frame_to_encode = cv2.resize(
                frame_to_encode,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        jpeg_q = max(30, min(95, int(getattr(self.settings, "hud_jpeg_quality", 70))))
        success, buffer = cv2.imencode(".jpg", frame_to_encode, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_q])
        if not success:
            return None
        return base64.b64encode(buffer).decode("ascii")

    def _compute_part_colors(self, angles: PoseAngles) -> Dict[str, str]:
        """Return per-part color levels {'left_arm','right_arm','left_leg','right_leg','torso'}.
        Levels: 'green' | 'yellow' | 'red', derived from deviation vs target thresholds.
        """
        thresholds = self._thresholds.get(self.exercise, self._thresholds["squat"])
        down = thresholds["down"]
        up = thresholds["up"]
        target_current = up if self.phase == "up" else down
        # Range-based margin scales with exercise
        range_span = max(10.0, abs(up - down))
        margin = max(5.0, range_span * 0.10)

        def level_for_error(err: float) -> str:
            if err <= margin:
                return "green"
            if err <= 2 * margin:
                return "yellow"
            return "red"

        # Compute per-part errors
        parts: Dict[str, float] = {}
        # Legs: only relevant for squat; use individual knees vs current target
        if self.exercise == "squat":
            if angles.left_knee is not None:
                parts["left_leg"] = abs(float(angles.left_knee) - target_current)
            if angles.right_knee is not None:
                parts["right_leg"] = abs(float(angles.right_knee) - target_current)
        # Arms: push-up primary is elbow; in otros ejercicios, mantén verde salvo datos presentes
        if angles.left_elbow is not None:
            parts.setdefault("left_arm", abs(float(angles.left_elbow) - target_current) if self.exercise == "pushup" else 0.0)
        if angles.right_elbow is not None:
            parts.setdefault("right_arm", abs(float(angles.right_elbow) - target_current) if self.exercise == "pushup" else 0.0)
        # Torso: penaliza inclinación excesiva (squat) o falta de flexión (crunch)
        torso_err = 0.0
        if self.exercise == "squat":
            tf = float(angles.torso_forward or 0.0)
            torso_err = max(0.0, tf - 25.0)  # >25° se considera excesivo
        elif self.exercise == "crunch":
            # Usa alineación hombro-cadera como indicador de flexión del tronco
            if angles.shoulder_hip_alignment is not None:
                torso_err = abs(float(angles.shoulder_hip_alignment) - target_current)
        elif self.exercise == "pushup":
            # Torso caído arqueado: torsión pequeña implica peor (usar inverso)
            tf = float(angles.torso_forward or 0.0)
            torso_err = max(0.0, 10.0 - tf)
        parts["torso"] = parts.get("torso", 0.0) + torso_err

        # Default greens for missing parts
        for k in ("left_arm", "right_arm", "left_leg", "right_leg", "torso"):
            parts.setdefault(k, 0.0)

        return {k: level_for_error(v) for k, v in parts.items()}

    def get_fps_avg(self) -> float:
        if not self._fps_window:
            return 0.0
        return sum(self._fps_window) / len(self._fps_window)

    def get_latency_samples_count(self) -> int:
        return len(self._latencies)

    # --- context -------------------------------------------------------

    def __del__(self) -> None:  # pragma: no cover
        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        try:
            if self._pose and hasattr(self._pose, "close"):
                self._pose.close()
        except Exception:
            pass
