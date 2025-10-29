"""SessionRecorder: captures posture timeline during a session window.

- Samples PoseEstimator.analyze_frame() at a fixed rate
- Stores list of samples with t (seconds since start), primary angle, rep_count, is_rep, latency_ms, fps
- Designed to continue through pauses and stop on session stop
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.vision.pipeline import PoseEstimator


@dataclass
class PostureSample:
    t: float
    angle: Optional[float]
    rep_count: int
    is_rep: int
    latency_ms: float
    fps: float


class SessionRecorder:
    def __init__(self, pose_estimator: PoseEstimator, sample_hz: float = 5.0) -> None:
        self.pose_estimator = pose_estimator
        self.sample_hz = max(0.5, float(sample_hz))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._start_ts: Optional[float] = None
        self._samples: List[PostureSample] = []
        self._last_rep: Optional[int] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._samples = []
        self._last_rep = None
        self._stop.clear()
        self._start_ts = time.perf_counter()
        self._thread = threading.Thread(target=self._run, name="SessionRecorder", daemon=True)
        self._thread.start()

    def _primary_angle(self, exercise: str, angles: dict) -> Optional[float]:
        def avg(vals: List[float]) -> Optional[float]:
            return sum(vals) / len(vals) if vals else None
        if exercise == "squat":
            c = [v for v in (angles.get("left_knee"), angles.get("right_knee")) if v is not None]
            return avg([float(x) for x in c]) if c else None
        if exercise == "pushup":
            c = [v for v in (angles.get("left_elbow"), angles.get("right_elbow")) if v is not None]
            return avg([float(x) for x in c]) if c else None
        # crunch
        hips = [v for v in (angles.get("left_hip"), angles.get("right_hip")) if v is not None]
        if hips:
            return avg([float(x) for x in hips])
        sha = angles.get("shoulder_hip_alignment")
        return float(sha) if sha is not None else None

    def _run(self) -> None:
        dt = 1.0 / self.sample_hz
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                res = self.pose_estimator.analyze_frame()
                exercise = (res.exercise or "").lower()
                angle = self._primary_angle(exercise, res.angles.__dict__)
                rc = int(res.rep_count or 0)
                is_rep = 1 if (self._last_rep is not None and rc > self._last_rep) else 0
                self._last_rep = rc
                t_rel = (t0 - (self._start_ts or t0))
                self._samples.append(PostureSample(t=t_rel, angle=angle, rep_count=rc, is_rep=is_rep, latency_ms=float(res.latency_ms), fps=float(res.fps)))
            except Exception:
                pass
            # sleep to maintain ~sample_hz
            t1 = time.perf_counter()
            remain = dt - (t1 - t0)
            if remain > 0:
                time.sleep(remain)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def get_samples(self) -> List[PostureSample]:
        return list(self._samples)

    def reset(self) -> None:
        self._samples = []
        self._last_rep = None
        self._start_ts = None
