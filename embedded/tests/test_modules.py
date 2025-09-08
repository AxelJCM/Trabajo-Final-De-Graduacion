from __future__ import annotations

from app.trainer.engine import TrainerEngine
from app.vision.pipeline import PoseEstimator


def test_trainer_basic():
    eng = TrainerEngine()
    r = eng.generate_routine("u1", {"heart_rate_bpm": 100})
    assert r.duration_min in (12, 15, 18)
    assert len(r.blocks) >= 3


def test_pose_estimator():
    pe = PoseEstimator()
    out = pe.analyze_frame()
    assert out.fps > 0
    assert len(out.joints) >= 1