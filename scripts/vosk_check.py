#!/usr/bin/env python3
"""Quick Vosk pipeline check using sounddevice.

Usage (PowerShell on Windows):
  # Ensure your venv is activated and deps installed
  # Optionally set VOSK_MODEL_PATH if the model is not autodetected
    # Default device=3; override with --device N
    python scripts/vosk_check.py --device 3

On Linux/Raspberry Pi (bash):
    PYTHONPATH=embedded python scripts/vosk_check.py --device 3
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
    p.add_argument("--device", type=int, default=3, help="Indice del micro (sounddevice)")
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
    # Log selected device info; do not auto-switch
    try:
        dinfo = sd.query_devices(args.device)
        name = dinfo.get("name")
        max_in = dinfo.get("max_input_channels")
        def_sr = dinfo.get("default_samplerate")
        print(f"[CHECK] Device fijado: index={args.device} name='{name}' max_input_channels={max_in} default_sr={def_sr}")
    except Exception as exc:
        print(f"[CHECK] No se pudo consultar dispositivos (se usara index={args.device}): {exc}")

    channels = 1
    stream = None
    try:
        stream = sd.RawInputStream(
            samplerate=args.rate,
            blocksize=8000,
            channels=channels,
            dtype="int16",
            device=args.device,
            callback=callback,
        )
        stream.start()
    except Exception as exc1:
        # Fallback to default samplerate
        try:
            d = sd.query_devices(args.device)
            def_sr = int(float(d.get("default_samplerate") or args.rate))
        except Exception:
            def_sr = args.rate
        if def_sr != args.rate:
            try:
                print(f"[CHECK] Reintentando con sample_rate={def_sr}")
                stream = sd.RawInputStream(
                    samplerate=def_sr,
                    blocksize=8000,
                    channels=channels,
                    dtype="int16",
                    device=args.device,
                    callback=callback,
                )
                stream.start()
                recognizer = vosk.KaldiRecognizer(model, def_sr)
            except Exception as exc2:
                # Try channels=2
                try:
                    print(f"[CHECK] Reintentando con channels=2 y sample_rate={def_sr}")
                    stream = sd.RawInputStream(
                        samplerate=def_sr,
                        blocksize=8000,
                        channels=2,
                        dtype="int16",
                        device=args.device,
                        callback=callback,
                    )
                    stream.start()
                    channels = 2
                    recognizer = vosk.KaldiRecognizer(model, def_sr)
                except Exception as exc3:
                    raise SystemExit(
                        f"[CHECK] No se pudo abrir audio: {exc1} | fallback_sr={def_sr} -> {exc2} | fallback_channels=2 -> {exc3}"
                    )
        else:
            # Try channels=2 with original rate
            try:
                print(f"[CHECK] Reintentando con channels=2")
                stream = sd.RawInputStream(
                    samplerate=args.rate,
                    blocksize=8000,
                    channels=2,
                    dtype="int16",
                    device=args.device,
                    callback=callback,
                )
                stream.start()
                channels = 2
            except Exception as exc2:
                raise SystemExit(f"[CHECK] No se pudo abrir audio: {exc1} | channels=2 -> {exc2}")

    try:
        while True:
            data = audio_q.get()
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                print(json.dumps(result, ensure_ascii=False))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if stream:
                stream.stop()
                stream.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
