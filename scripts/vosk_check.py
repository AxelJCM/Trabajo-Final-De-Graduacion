#!/usr/bin/env python3
"""Quick Vosk pipeline check using sounddevice.

Usage (PowerShell on Windows):
  # Ensure your venv is activated and deps installed
  # Optionally set VOSK_MODEL_PATH if the model is not autodetected
  # Default device=2; override with --device N
  python scripts/vosk_check.py --device 2

On Linux/Raspberry Pi (bash):
  PYTHONPATH=embedded python scripts/vosk_check.py --device 2
"""
from __future__ import annotations

import argparse
import json
import queue
import sys

import sounddevice as sd
import vosk


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--device", type=int, default=2, help="Indice del micro (sounddevice)")
    p.add_argument("--rate", type=int, default=16000)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    model = None
    # Try environment variable first
    import os
    model_path = os.getenv("VOSK_MODEL_PATH")
    if not model_path:
        # Try to auto-detect repo-local model folder
        from pathlib import Path
        here = Path(__file__).resolve()
        for parent in list(here.parents)[:5]:
            candidate = parent / "vosk-model-small-es-0.42"
            if candidate.exists():
                model_path = str(candidate)
                break
    if not model_path:
        raise SystemExit("VOSK_MODEL_PATH no configurado y no se encontro 'vosk-model-small-es-0.42' en el repo")

    model = vosk.Model(model_path)
    recognizer = vosk.KaldiRecognizer(model, args.rate)

    audio_q: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):  # pragma: no cover
        if status:
            print(status, file=sys.stderr)
        audio_q.put(bytes(indata))

    print(">>> Probando Vosk, habla cerca del micro. Ctrl+C para salir. (device=%s, rate=%s)" % (args.device, args.rate))
    with sd.RawInputStream(
        samplerate=args.rate,
        blocksize=8000,
        channels=1,
        dtype="int16",
        device=args.device,
        callback=callback,
    ):
        try:
            while True:
                data = audio_q.get()
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    print(json.dumps(result, ensure_ascii=False))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
