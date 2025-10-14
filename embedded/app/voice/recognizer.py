"""Voice control recognizer with offline Vosk support and customizable intents."""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from typing import Optional, Dict

from loguru import logger

from app.core.config import get_settings
from app.training.datasets import load_voice_commands, save_voice_commands, register_voice_synonym

try:  # Optional dependency
    import vosk  # type: ignore
except Exception:  # pragma: no cover
    vosk = None  # type: ignore

_DEFAULT_COMMANDS: Dict[str, str] = {
    "start": "start",
    "iniciar": "start",
    "inicia": "start",
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
    "inicia rutina": "start_routine",
    "iniciar rutina": "start_routine",
    "comienza rutina": "start_routine",
}

_COMMANDS_CACHE: Dict[str, str] = {}


def _load_commands() -> Dict[str, str]:
    global _COMMANDS_CACHE
    if not _COMMANDS_CACHE:
        data = load_voice_commands()
        mapping = {**_DEFAULT_COMMANDS, **{k.lower(): v for k, v in data.items()}}
        _COMMANDS_CACHE = mapping
    return _COMMANDS_CACHE


def refresh_commands_cache() -> None:
    global _COMMANDS_CACHE
    _COMMANDS_CACHE = {}
    _load_commands()


def add_voice_synonym(utterance: str, intent: str) -> None:
    register_voice_synonym(utterance, intent)
    refresh_commands_cache()


class VoiceRecognizer:
    """Voice recognition component with optional Vosk backend."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._vosk_model = None
        self._load_vosk_model()

    def _load_vosk_model(self) -> None:
        if not getattr(self.settings, "use_vosk_offline", False):
            return
        if vosk is None:
            logger.warning("Vosk library not available; offline recognition disabled")
            return
        model_path_env = getattr(self.settings, "vosk_model_path", None) or os.getenv("VOSK_MODEL_PATH")
        if not model_path_env:
            logger.warning("VOSK_MODEL_PATH not configured; offline recognition disabled")
            return
        path = Path(model_path_env).expanduser()
        if not path.exists():
            logger.warning("Vosk model path {} does not exist", path)
            return
        try:
            self._vosk_model = vosk.Model(str(path))
            logger.info("Loaded Vosk model from {}", path)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to load Vosk model: {}", exc)
            self._vosk_model = None

    def listen_and_recognize(self, wav_path: Optional[str] = None, timeout: float = 5.0) -> Optional[str]:  # pragma: no cover - audio capture not tested
        logger.info("voice listening timeout={}s wav_path={}", timeout, wav_path)
        if wav_path:
            return self.recognize_from_wav(wav_path)
        # Placeholder for live microphone recording
        logger.warning("Live microphone capture not implemented; provide wav_path")
        return None

    def recognize_from_wav(self, wav_path: str) -> Optional[str]:
        if self._vosk_model is None:
            logger.warning("Vosk model not loaded; cannot transcribe {}", wav_path)
            return None
        try:
            with wave.open(wav_path, "rb") as wf:
                if wf.getnchannels() != 1:
                    logger.warning("Audio {} must be mono for Vosk; channels={}", wav_path, wf.getnchannels())
                rec = vosk.KaldiRecognizer(self._vosk_model, wf.getframerate())
                rec.SetWords(True)
                while True:
                    data = wf.readframes(4000)
                    if len(data) == 0:
                        break
                    rec.AcceptWaveform(data)
                result = json.loads(rec.FinalResult())
                text = (result.get("text") or "").strip()
                logger.info("Vosk transcription='{}'", text)
                return text or None
        except Exception as exc:
            logger.error("Failed to transcribe {}: {}", wav_path, exc)
            return None


def map_utterance_to_intent(utterance: str) -> Optional[str]:
    """Map a plaintext utterance to a known intent using configurable synonyms."""
    if not utterance:
        return None
    mapping = _load_commands()
    u = utterance.strip().lower()
    if u in mapping:
        return mapping[u]
    # simple heuristics
    if "rutina" in u and ("inicia" in u or "iniciar" in u or "comienza" in u):
        return "start_routine"
    return None
