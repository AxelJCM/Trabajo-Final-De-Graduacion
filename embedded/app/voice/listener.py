"""Background listener that maps spoken commands to intents and triggers actions."""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.voice.recognizer import VoiceRecognizer, map_utterance_to_intent

try:  # Optional dependency (already required by mediapipe)
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover
    sd = None  # type: ignore

try:  # Optional dependency
    import vosk  # type: ignore
except Exception:  # pragma: no cover
    vosk = None  # type: ignore

try:  # Requests for triggering API endpoints
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


@dataclass
class ListenerConfig:
    base_url: str = "http://127.0.0.1:8000"
    device: Optional[int] = None
    rate: int = 16000
    blocksize: int = 8000
    silence_window: float = 1.0
    dedupe_seconds: float = 2.0


class VoiceIntentListener:
    """Runs in a background thread listening for intents."""

    def __init__(self, config: ListenerConfig) -> None:
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._recognizer = VoiceRecognizer()
        self._vosk_model = self._recognizer._vosk_model
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._last_intent: Optional[str] = None
        self._last_intent_ts: float = 0.0
        self._exercise_cycle = ["squat", "pushup", "crunch"]
        self._cycle_index = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if sd is None or vosk is None:
            logger.warning("sounddevice/vosk indisponibles; listener de voz deshabilitado")
            return
        if self._vosk_model is None:
            logger.warning("Modelo Vosk no cargado; listener de voz deshabilitado")
            return
        if requests is None:
            logger.warning("Requests no disponible; listener de voz deshabilitado")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="VoiceIntentListener", daemon=True)
        self._thread.start()
        logger.info("Voice intent listener iniciado (device={} rate={})", self.config.device, self.config.rate)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Voice intent listener detenido")

    # --- internal helpers ---

    def _trigger_intent(self, intent: str) -> None:
        if requests is None:
            return
        base = self.config.base_url.rstrip("/")

        def _post(path: str, payload: Optional[dict]) -> None:
            url = base + path
            try:
                resp = requests.post(url, json=payload, timeout=5)
                resp.raise_for_status()
                logger.info("Intent '{}' ejecutado -> {}", intent, url)
            except Exception as exc:  # pragma: no cover
                logger.warning("Error ejecutando intent '{}': {}", intent, exc)

        if intent in {"start", "start_routine"}:
            if intent == "start_routine":
                self._cycle_index = 0
            exercise = self._exercise_cycle[self._cycle_index]
            _post("/session/start", {"exercise": exercise, "reset": True})
        elif intent == "pause":
            _post("/session/pause", {})
        elif intent == "stop":
            _post("/session/stop", {})
        elif intent == "next":
            self._cycle_index = (self._cycle_index + 1) % len(self._exercise_cycle)
            exercise = self._exercise_cycle[self._cycle_index]
            _post("/session/exercise", {"exercise": exercise, "reset": True})
        else:
            logger.info("Intent '{}' detectado (sin accion configurada)", intent)

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # pragma: no cover - callback
        if status:
            logger.debug("Audio status: {}", status)
        self._audio_queue.put(bytes(indata))

    def _run(self) -> None:
        try:
            vosk_recognizer = vosk.KaldiRecognizer(self._vosk_model, self.config.rate)
        except Exception as exc:  # pragma: no cover
            logger.error("No se pudo crear reconocedor Vosk: {}", exc)
            return

        block_seconds = self.config.blocksize / float(self.config.rate)
        buffer_since_speech = 0.0

        stream = None
        try:
            stream = sd.RawInputStream(
                samplerate=self.config.rate,
                blocksize=self.config.blocksize,
                device=self.config.device,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            stream.start()
        except Exception as exc:  # pragma: no cover
            logger.error("No se pudo abrir stream de audio: {}", exc)
            return

        try:
            while not self._stop_event.is_set():
                try:
                    data = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if vosk_recognizer.AcceptWaveform(data):
                    result = json.loads(vosk_recognizer.Result())
                    text = (result.get("text") or "").strip()
                    if text:
                        logger.info("Texto detectado: '{}'", text)
                        intent = map_utterance_to_intent(text)
                        if intent:
                            now = time.time()
                            if self._last_intent == intent and (now - self._last_intent_ts) < self.config.dedupe_seconds:
                                logger.debug("Intent '{}' ignorado (duplicado)", intent)
                            else:
                                self._trigger_intent(intent)
                                self._last_intent = intent
                                self._last_intent_ts = now
                        else:
                            logger.info("Intent no reconocido para '{}'", text)
                    vosk_recognizer.Reset()
                    buffer_since_speech = 0.0
                else:
                    buffer_since_speech += block_seconds
                    if buffer_since_speech >= self.config.silence_window:
                        vosk_recognizer.Reset()
                        buffer_since_speech = 0.0
        finally:
            try:
                if stream:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
