"""Training data collection endpoints for voice and posture modules."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from loguru import logger

from app.api.schemas import Envelope
from app.training.datasets import save_pose_sample, save_voice_sample, register_voice_synonym
from app.api.routers.posture import pose_estimator
from app.voice.recognizer import map_utterance_to_intent, refresh_commands_cache

router = APIRouter()


class PoseSampleInput(BaseModel):
    label: str = Field(..., description="Nombre del ejercicio o clase del sample")
    notes: Optional[str] = Field(None, description="Notas opcionales del sample")


class VoiceSampleInput(BaseModel):
    transcript: str = Field(..., description="Transcripción del audio")
    intent: Optional[str] = Field(None, description="Intent esperado (opcional si se puede inferir)")
    audio_path: Optional[str] = Field(None, description="Ruta al archivo de audio asociado")
    add_synonym: bool = Field(False, description="Agregar transcript como sinónimo al intent")


@router.post("/training/pose/sample", response_model=Envelope)
async def training_pose_sample(payload: PoseSampleInput) -> Envelope:
    result = pose_estimator.analyze_frame()
    joints = [
        {"name": j.name, "x": j.x, "y": j.y, "score": j.score}
        for j in result.joints
    ]
    angles = {
        "left_elbow": result.angles.left_elbow,
        "right_elbow": result.angles.right_elbow,
        "left_knee": result.angles.left_knee,
        "right_knee": result.angles.right_knee,
        "shoulder_hip_alignment": result.angles.shoulder_hip_alignment,
    }
    metadata = {
        "quality": result.quality,
        "exercise": result.exercise,
        "phase": result.phase,
        "rep_count": result.rep_count,
        "fps": result.fps,
        "notes": payload.notes,
    }
    path = save_pose_sample(payload.label, joints, angles, metadata)
    return Envelope(success=True, data={"path": str(path), "quality": result.quality})


@router.post("/training/voice/sample", response_model=Envelope)
async def training_voice_sample(payload: VoiceSampleInput) -> Envelope:
    intent = payload.intent or map_utterance_to_intent(payload.transcript)
    if not intent:
        raise HTTPException(status_code=400, detail="intent_unknown")
    path = save_voice_sample(payload.transcript, intent, payload.audio_path)
    if payload.add_synonym:
        register_voice_synonym(payload.transcript, intent)
        refresh_commands_cache()
        logger.info("Added synonym '{}' -> {}", payload.transcript, intent)
    return Envelope(success=True, data={"path": str(path), "intent": intent})
