"""Voice control recognizer with Vosk transcription and command mapping."""
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from typing import Dict, Optional
import unicodedata

from loguru import logger

from app.core.config import get_settings
from app.training.datasets import load_voice_commands, register_voice_synonym

try:  # Optional dependency
    import vosk  # type: ignore
except Exception:  # pragma: no cover
    vosk = None  # type: ignore

def _normalize_key(value: str) -> str:
    base = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(ch for ch in base if not unicodedata.combining(ch))


_DEFAULT_COMMANDS: Dict[str, str] = {
    "iniciar": "start",
    "siguiente": "next",
    "pausa": "pause",
    "detener": "stop",
}

_COMMANDS_CACHE: Dict[str, str] = {}

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
        candidate_paths = []
        if model_path_env:
            candidate_paths.append(Path(model_path_env).expanduser())
        # Fallback: try to locate a bundled or sibling model directory
        try:
            here = Path(__file__).resolve()
            for parent in list(here.parents)[:5]:
                # Check workspace root for common folder name
                for name in ("vosk-model-small-es-0.42", "vosk-model-es-0.42"):
                    candidate_paths.append(parent / name)
        except Exception:
            pass

        path = next((p for p in candidate_paths if p and p.exists()), None)
        if path is None:
            logger.warning("Vosk model path not found; set VOSK_MODEL_PATH or place 'vosk-model-small-es-0.42' at repo root")
            return
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
        """Compatibility shim used by tests; supports either a path or a timeout number.

        If ``wav_path`` is a string path, transcribe that file. If it's a number,
        treat it as timeout for live capture (not implemented) and return None.
        """
        # Back-compat with tests that pass a float as first arg
        if isinstance(wav_path, (int, float)):
            timeout = float(wav_path)
            wav_path = None
        logger.info("voice listening timeout={}s wav_path={}", timeout, wav_path)
        if isinstance(wav_path, (str, os.PathLike)):
            return self.recognize_from_wav(str(wav_path))
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
    """Map a plaintext utterance to a known intent using synonym mapping."""
    if not utterance:
        return None
    mapping = _load_commands()
    normalized = _normalize_key(utterance)
    if normalized in mapping:
        return mapping[normalized]
    # Fallback: allow substring match when the utterance contains the keyword
    for key, intent in mapping.items():
        if key and key in normalized:
            return intent
    return None
