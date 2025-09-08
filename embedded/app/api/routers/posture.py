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
    result: PostureOutput = pose_estimator.analyze_frame()
    logger.info("posture fps={}", result.fps)
    return Envelope(success=True, data=result.model_dump())
