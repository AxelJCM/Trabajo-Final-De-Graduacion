from __future__ import annotations

from app.vision.pipeline import PoseEstimator

# TrainerEngine removed per scope change


def test_pose_estimator():
    pe = PoseEstimator()
    out = pe.analyze_frame()
    assert out.fps > 0
    assert len(out.joints) >= 1
    assert isinstance(out.rep_totals, dict)
    assert out.feedback_code is not None
