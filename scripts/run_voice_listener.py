#!/usr/bin/env python3
"""Listen to microphone input and trigger intents in real time."""
from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from typing import Dict, Optional, Tuple

import requests
import sounddevice as sd

from app.voice.recognizer import VoiceRecognizer, map_utterance_to_intent

try:
    import vosk  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"[VOICE] La libreria vosk no esta disponible: {exc}")
    sys.exit(1)

DEFAULT_RATE = 16000
DEFAULT_DEVICE = None  # use default device if not specified

INTENT_ACTIONS: Dict[str, Tuple[str, str, Optional[dict]]] = {
    "start": ("POST", "/session/start", {"exercise": "squat"}),
    "start_routine": ("POST", "/session/start", {"exercise": "squat"}),
    "pause": ("POST", "/session/stop", None),
    "stop": ("POST", "/session/stop", None),
    # "next" could hit another endpoint; for now just log
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Listener de voz en tiempo real")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL base del backend")
    parser.add_argument("--device", type=int, default=DEFAULT_DEVICE, help="Indice del dispositivo de audio (arecord -l / sd.query_devices)")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, help="Frecuencia de muestreo")
    parser.add_argument("--blocksize", type=int, default=8000, help="Tamaño de bloque de audio")
    parser.add_argument("--silence-window", type=float, default=1.0, help="Segundos de silencio para resetear reconocimiento")
    parser.add_argument("--dedupe-seconds", type=float, default=2.0, help="Ignorar mismos intents detectados en este intervalo")
    return parser.parse_args()


def trigger_intent(intent: str, base_url: str) -> None:
    action = INTENT_ACTIONS.get(intent)
    if not action:
        print(f"[VOICE] Intent '{intent}' detectado (sin accion asociada)")
        return
    method, path, payload = action
    url = base_url.rstrip("/") + path
    try:
        if method.upper() == "POST":
            resp = requests.post(url, json=payload, timeout=5)
        else:
            resp = requests.get(url, params=payload, timeout=5)
        resp.raise_for_status()
        print(f"[VOICE] Intent '{intent}' ejecutado -> {url}")
    except Exception as exc:
        print(f"[VOICE] Error ejecutando intent '{intent}': {exc}")


def main() -> None:
    args = parse_args()
    audio_queue: "queue.Queue[bytes]" = queue.Queue()

    recognizer = VoiceRecognizer()
    vosk_model = recognizer._vosk_model
    if vosk_model is None:
        print("[VOICE] No se cargó el modelo Vosk. Verifica USE_VOSK_OFFLINE/VOSK_MODEL_PATH.")
        sys.exit(1)

    try:
        rec = vosk.KaldiRecognizer(vosk_model, args.rate)
    except Exception as exc:
        print(f"[VOICE] No se pudo crear el reconocedor Vosk: {exc}")
        sys.exit(1)

    last_intent: Optional[str] = None
    last_intent_ts: float = 0.0

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"[VOICE] Status de audio: {status}")
        audio_queue.put(bytes(indata))

    print("[VOICE] Escuchando... (Ctrl+C para salir)")

    with sd.RawInputStream(
        samplerate=args.rate,
        blocksize=args.blocksize,
        device=args.device,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        buffer_since_speech = 0.0
        block_seconds = args.blocksize / args.rate
        while True:
            data = audio_queue.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = (result.get("text") or "").strip()
                if text:
                    print(f"[VOICE] Texto: '{text}'")
                    intent = map_utterance_to_intent(text)
                    if intent:
                        now = time.time()
                        if last_intent == intent and (now - last_intent_ts) < args.dedupe_seconds:
                            print(f"[VOICE] Intent '{intent}' ignorado (duplicado)")
                        else:
                            trigger_intent(intent, args.base_url)
                            last_intent = intent
                            last_intent_ts = now
                    else:
                        print("[VOICE] Intent no reconocido")
                rec.Reset()
                buffer_since_speech = 0.0
            else:
                buffer_since_speech += block_seconds
                if buffer_since_speech >= args.silence_window:
                    rec.Reset()
                    buffer_since_speech = 0.0


if __name__ == "__main__":
    main()
