"""Voice control recognizer with optional Vosk transcription and intent classifier."""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from typing import Dict, Optional, Tuple
import unicodedata

from loguru import logger

from app.core.config import get_settings
from app.training.datasets import load_voice_commands, register_voice_synonym

try:  # Optional dependency
    import vosk  # type: ignore
except Exception:  # pragma: no cover
    vosk = None  # type: ignore

try:  # Optional dependency for classifier support
    import joblib  # type: ignore
except Exception:  # pragma: no cover
    joblib = None  # type: ignore

def _normalize_key(value: str) -> str:
    base = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(ch for ch in base if not unicodedata.combining(ch))


_DEFAULT_COMMANDS: Dict[str, str] = {
    "iniciar": "start",
    "iniciar sesion": "start",
    "inicia sesion": "start",
    "comenzar sesion": "start",
    "empezar sesion": "start",
    "siguiente": "next",
    "pausa": "pause",
    "pausar": "pause",
    "detener": "stop",
    "detener sesion": "stop",
    "terminar": "stop",
    "terminar sesion": "stop",
}

_COMMANDS_CACHE: Dict[str, str] = {}
_CLASSIFIER_CACHE: Optional[Tuple[object, object]] = None


def _load_commands() -> Dict[str, str]:
    global _COMMANDS_CACHE
    if not _COMMANDS_CACHE:
        data = load_voice_commands()
        mapping: Dict[str, str] = {}
        for key, value in _DEFAULT_COMMANDS.items():
            mapping[_normalize_key(key)] = value
        for key, value in data.items():
            mapping[_normalize_key(key)] = value
        _COMMANDS_CACHE = mapping
    return _COMMANDS_CACHE


def refresh_commands_cache() -> None:
    global _COMMANDS_CACHE
    _COMMANDS_CACHE = {}
    _load_commands()


def add_voice_synonym(utterance: str, intent: str) -> None:
    register_voice_synonym(utterance, intent)
    refresh_commands_cache()


def _load_classifier() -> Optional[Tuple[object, object]]:
    """Return cached (vectorizer, model) tuple if available."""
    global _CLASSIFIER_CACHE
    if _CLASSIFIER_CACHE is not None:
        return _CLASSIFIER_CACHE
    settings = get_settings()
    model_path = getattr(settings, "voice_intent_model_path", None) or os.getenv("VOICE_INTENT_MODEL_PATH")
    if not model_path:
        return None
    if joblib is None:
        logger.warning("joblib no disponible; no se puede cargar modelo de intent")
        return None
    path = Path(model_path).expanduser()
    if not path.exists():
        logger.warning("Modelo de intent de voz no encontrado: {}", path)
        return None
    try:
        payload = joblib.load(path)
        vectorizer = payload.get("vectorizer")
        model = payload.get("model")
        if vectorizer is None or model is None:
            raise ValueError("El modelo no contiene vectorizer/model")
        _CLASSIFIER_CACHE = (vectorizer, model)
        logger.info("Modelo de intent de voz cargado desde {}", path)
    except Exception as exc:  # pragma: no cover
        logger.error("No se pudo cargar modelo de intent de voz: {}", exc)
        _CLASSIFIER_CACHE = None
    return _CLASSIFIER_CACHE


def refresh_intent_model_cache() -> None:
    global _CLASSIFIER_CACHE
    _CLASSIFIER_CACHE = None
    _load_classifier()


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

    def listen_and_recognize(self, wav_path: Optional[str] = None, timeout: float = 5.0) -> Optional[str]:  # pragma: no cover
        logger.info("voice listening timeout={}s wav_path={}", timeout, wav_path)
        if wav_path:
            return self.recognize_from_wav(wav_path)
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
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to transcribe {}: {}", wav_path, exc)
            return None


def map_utterance_to_intent(utterance: str) -> Optional[str]:
    """Map a plaintext utterance to a known intent using synonyms or classifier."""
    if not utterance:
        return None
    mapping = _load_commands()
    normalized = _normalize_key(utterance)
    if normalized in mapping:
        return mapping[normalized]
    classifier = _load_classifier()
    if classifier and normalized:
        vectorizer, model = classifier
        try:
            prediction = model.predict(vectorizer.transform([normalized]))[0]
            logger.info("Intent predicho mediante modelo: '{}' -> '{}'", normalized, prediction)
            return str(prediction)
        except Exception as exc:  # pragma: no cover
            logger.warning("El modelo de intent fallo: {}", exc)
    return None
