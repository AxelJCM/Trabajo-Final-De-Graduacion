"""Posture analysis endpoint router.

Uses the vision module to compute pose keypoints and feedback.
"""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.api.schemas import Envelope, PostureInput, PostureOutput
from app.vision.pipeline import PoseEstimator

router = APIRouter()

pose_estimator = PoseEstimator()


@router.post("/posture", response_model=Envelope)
async def posture_endpoint(payload: PostureInput) -> Envelope:
    """Return posture analysis for the current frame.

    For now, this pulls from the camera internally and returns dummy joints.
    """
    result = pose_estimator.analyze_frame()
    logger.info(
        "posture fps={} reps={} phase={} latency_p95={}",
        result.fps,
        result.rep_count,
        result.phase,
        result.latency_ms_p95,
    )
    payload = PostureOutput.model_validate(result.to_dict())
    return Envelope(success=True, data=payload.model_dump())
