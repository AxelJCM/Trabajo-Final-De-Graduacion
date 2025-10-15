#!/usr/bin/env python3
"""Record audio from microphone and register it as a voice training sample."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests


DEFAULT_DEVICE = "plughw:3,0"  # adjust if your mic uses another card/device
DEFAULT_RATE = 16000
DEFAULT_DURATION = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grabar audio y registrarlo como sample de voz")
    parser.add_argument("transcript", help="Transcripcion de la frase")
    parser.add_argument("intent", help="Intent (start, pause, start_routine, etc.)")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Dispositivo ALSA (default: %(default)s)")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, help="Frecuencia de muestreo Hz (default: %(default)s)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="Duracion en segundos (default: %(default)s)")
    parser.add_argument("--output", default="recordings", help="Carpeta donde guardar el wav generado")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL del backend")
    parser.add_argument("--token", help="X-API-Key si aplica", default=None)
    parser.add_argument("--no-synonym", action="store_true", help="Registrar sample sin agregar sinonimo")
    return parser.parse_args()


def record_audio(path: Path, device: str, rate: int, duration: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "arecord",
        "-D", device,
        "-f", "S16_LE",
        "-c", "1",
        "-r", str(rate),
        "-d", str(duration),
        str(path),
    ]
    print("Grabando...", " ".join(cmd))
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        raise SystemExit(f"arecord fallo con codigo {res.returncode}")
    print(f"Audio guardado en {path}")


def register_sample(transcript: str, intent: str, audio_path: Path, base_url: str, token: str | None, add_synonym: bool) -> dict[str, Any]:
    payload = {
        "transcript": transcript,
        "intent": intent,
        "audio_path": str(audio_path),
        "add_synonym": add_synonym,
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Key"] = token
    url = f"{base_url.rstrip('/')}/training/voice/sample"
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise SystemExit(f"Error del backend: {data}")
    return data["data"]


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output)
    filename = f"{args.intent}_{args.transcript.replace(' ', '_')}.wav"
    audio_path = output_dir / filename

    record_audio(audio_path, args.device, args.rate, args.duration)
    result = register_sample(
        transcript=args.transcript,
        intent=args.intent,
        audio_path=audio_path,
        base_url=args.base_url,
        token=args.token,
        add_synonym=not args.no_synonym,
    )
    print("Sample registrado:")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
