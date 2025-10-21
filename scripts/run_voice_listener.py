#!/usr/bin/env python3
"""Listen to microphone input and trigger intents in real time."""
from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from typing import Dict, Optional, Tuple
from pathlib import Path

# Ensure 'embedded' is on sys.path so that 'app.*' imports resolve even when running from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
EMBEDDED_DIR = REPO_ROOT / "embedded"
if str(EMBEDDED_DIR) not in sys.path:
    sys.path.insert(0, str(EMBEDDED_DIR))

import requests
import sounddevice as sd

from app.voice.recognizer import VoiceRecognizer, map_utterance_to_intent

try:
    import vosk  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"[VOICE] Vosk library not available: {exc}")
    sys.exit(1)

DEFAULT_RATE = 16000
DEFAULT_DEVICE = 2

INTENT_ACTIONS: Dict[str, Tuple[str, str, Optional[dict]]] = {
    "start": ("POST", "/session/start", {"exercise": "squat"}),
    "pause": ("POST", "/session/pause", {}),
    "stop": ("POST", "/session/stop", {}),
    "next": ("POST", "/session/exercise", {"exercise": "pushup", "reset": True}),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time voice listener")
    parser.add_argument("--device", type=int, default=DEFAULT_DEVICE, help="Input device index (sounddevice)")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, help="Sample rate")
    parser.add_argument("--blocksize", type=int, default=8000, help="Audio block size")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--silence-window", type=float, default=1.0, help="Seconds of silence to reset recognizer")
    parser.add_argument("--dedupe-seconds", type=float, default=2.0, help="Ignore repeated intents for this window")
    return parser.parse_args()


def trigger_intent(intent: str, base_url: str) -> None:
    action = INTENT_ACTIONS.get(intent)
    if not action:
        print(f"[VOICE] Intent '{intent}' detected (no action configured)")
        return
    method, path, payload = action
    url = base_url.rstrip("/") + path
    try:
        if method.upper() == "POST":
            resp = requests.post(url, json=payload, timeout=5)
        else:
            resp = requests.get(url, params=payload, timeout=5)
        resp.raise_for_status()
        print(f"[VOICE] Intent '{intent}' executed -> {url}")
    except Exception as exc:
        print(f"[VOICE] Error executing intent '{intent}': {exc}")


def main() -> None:
    args = parse_args()
    audio_queue: "queue.Queue[bytes]" = queue.Queue()

    recognizer = VoiceRecognizer()
    vosk_model = recognizer._vosk_model
    if vosk_model is None:
        print("[VOICE] Vosk model not loaded. Check USE_VOSK_OFFLINE/VOSK_MODEL_PATH.")
        sys.exit(1)

    try:
        rec = vosk.KaldiRecognizer(vosk_model, args.rate)
    except Exception as exc:
        print(f"[VOICE] Could not create recognizer: {exc}")
        sys.exit(1)

    last_intent: Optional[str] = None
    last_intent_ts: float = 0.0
    channels = 1

    def audio_callback(indata, frames, time_info, status):  # pragma: no cover
        if status:
            print(f"[VOICE] Audio status: {status}")
        audio_queue.put(bytes(indata))

    print("[VOICE] Listening... (Ctrl+C to exit)")

    if args.device is None:
        args.device = DEFAULT_DEVICE
        print(f"[VOICE] Usando device por defecto: {args.device}")

    # Log selected device info; do not auto-switch
    try:
        dinfo = sd.query_devices(args.device)
        name = dinfo.get("name")
        max_in = dinfo.get("max_input_channels")
        def_sr = dinfo.get("default_samplerate")
        print(f"[VOICE] Device fijado: index={args.device} name='{name}' max_input_channels={max_in} default_sr={def_sr}")
    except Exception as exc:
        print(f"[VOICE] No se pudo consultar dispositivos (se usara index={args.device}): {exc}")

    # Try opening stream; fallback to device default samplerate when needed
    stream = None
    try:
        stream = sd.RawInputStream(
            samplerate=args.rate,
            blocksize=args.blocksize,
            device=args.device,
            dtype="int16",
            channels=channels,
            callback=audio_callback,
        )
        stream.start()
    except Exception as exc1:
        try:
            d = sd.query_devices(args.device)
            def_sr = int(float(d.get("default_samplerate") or args.rate))
        except Exception:
            def_sr = args.rate
        if def_sr != args.rate:
            try:
                print(f"[VOICE] Reintentando con sample_rate={def_sr} (device={args.device})")
                stream = sd.RawInputStream(
                    samplerate=def_sr,
                    blocksize=args.blocksize,
                    device=args.device,
                    dtype="int16",
                    channels=channels,
                    callback=audio_callback,
                )
                stream.start()
                rec = vosk.KaldiRecognizer(vosk_model, def_sr)
            except Exception as exc2:
                # Try channels=2
                try:
                    print(f"[VOICE] Reintentando con channels=2 y sample_rate={def_sr} (device={args.device})")
                    stream = sd.RawInputStream(
                        samplerate=def_sr,
                        blocksize=args.blocksize,
                        device=args.device,
                        dtype="int16",
                        channels=2,
                        callback=audio_callback,
                    )
                    stream.start()
                    channels = 2
                    rec = vosk.KaldiRecognizer(vosk_model, def_sr)
                except Exception as exc3:
                    raise SystemExit(
                        f"[VOICE] Could not open audio input (device={args.device}): {exc1} | fallback_sr={def_sr} -> {exc2} | fallback_channels=2 -> {exc3}"
                    ) from exc3
        else:
            # Try channels=2 with original sample rate
            try:
                print(f"[VOICE] Reintentando con channels=2 (device={args.device})")
                stream = sd.RawInputStream(
                    samplerate=args.rate,
                    blocksize=args.blocksize,
                    device=args.device,
                    dtype="int16",
                    channels=2,
                    callback=audio_callback,
                )
                stream.start()
                channels = 2
            except Exception as exc2:
                raise SystemExit(
                    f"[VOICE] Could not open audio input (device={args.device}): {exc1} | channels=2 -> {exc2}"
                ) from exc2

    try:
        buffer_since_speech = 0.0
        block_seconds = args.blocksize / args.rate
        while True:
            data = audio_queue.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = (result.get("text") or "").strip()
                if text:
                    print(f"[VOICE] Text: '{text}'")
                    intent = map_utterance_to_intent(text)
                    if intent:
                        now = time.time()
                        if last_intent == intent and (now - last_intent_ts) < args.dedupe_seconds:
                            print(f"[VOICE] Intent '{intent}' ignored (duplicate)")
                        else:
                            trigger_intent(intent, args.base_url)
                            last_intent = intent
                            last_intent_ts = now
                    else:
                        print("[VOICE] Intent not recognized")
                rec.Reset()
                buffer_since_speech = 0.0
            else:
                buffer_since_speech += block_seconds
                if buffer_since_speech >= args.silence_window:
                    rec.Reset()
                    buffer_since_speech = 0.0
    finally:
        if stream is not None:
            stream.stop()
            stream.close()


if __name__ == "__main__":
    main()
