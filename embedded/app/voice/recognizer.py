"""Voice control recognizer.

Provides offline Vosk or Google Speech API based recognition.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from app.core.config import get_settings


class VoiceRecognizer:
    """Stub for voice recognition component."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def listen_and_recognize(self, timeout: float = 5.0) -> Optional[str]:  # pragma: no cover - audio not testable
        logger.info("voice listening timeout={}s", timeout)
        if self.settings.use_vosk_offline:
            # TODO: integrate Vosk model
            return "iniciar rutina"
        # TODO: integrate Google Speech
        return None


def map_utterance_to_intent(utterance: str) -> Optional[str]:
    """Map a plaintext utterance to a known intent.

    Supported intents: start, pause, next, stop, volume_up, volume_down
    """
    if not utterance:
        return None
    u = utterance.strip().lower()
    table = {
        "start": "start",
        "iniciar": "start",
        "pause": "pause",
        "pausa": "pause",
        "next": "next",
        "siguiente": "next",
        "stop": "stop",
        "detener": "stop",
        "volume_up": "volume_up",
        "subir volumen": "volume_up",
        "volume_down": "volume_down",
        "bajar volumen": "volume_down",
    }
    return table.get(u)
"""Voice control interface using Vosk (offline) or Google Speech API.

Exposes Recognizer.listen_once() returning a command string.
"""
from __future__ import annotations

from loguru import logger

from app.core.config import get_settings


class Recognizer:
    """Simple voice recognizer wrapper.

    In production, initialize Vosk model or Google client.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def listen_once(self) -> str:
        """Listen to mic and return recognized command (stub)."""
        command = "start workout"  # placeholder
        logger.info("voice command recognized: {}", command)
        return command
