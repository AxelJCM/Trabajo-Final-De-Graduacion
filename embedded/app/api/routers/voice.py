"""Voice testing endpoints (device-less).

POST /voice/test accepts {"utterance": "start|pause|next|stop|volume_up|volume_down"}
and returns {success, data:{intent}, error} without requiring Vosk.
"""
from __future__ import annotations

from fastapi import APIRouter
from loguru import logger

from app.api.schemas import Envelope
from app.voice.recognizer import map_utterance_to_intent


router = APIRouter()


@router.post("/voice/test", response_model=Envelope)
async def voice_test(payload: dict) -> Envelope:
    utterance = (payload or {}).get("utterance", "")
    intent = map_utterance_to_intent(utterance)
    logger.info("voice test utterance='{}' -> intent='{}'", utterance, intent)
    if intent is None:
        return Envelope(success=False, data=None, error="unknown_intent")
    return Envelope(success=True, data={"intent": intent}, error=None)
