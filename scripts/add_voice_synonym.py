#!/usr/bin/env python3
"""Register a voice transcript/intention pair for training."""
from __future__ import annotations

import argparse
import json
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agregar sinonimo/intencion para el modulo de voz")
    parser.add_argument("transcript", help="Transcripcion del audio o frase")
    parser.add_argument("intent", help="Intent deseado (start, pause, start_routine, etc.)")
    parser.add_argument("--audio", help="Ruta al archivo de audio asociado", default=None)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL del backend (default: %(default)s)")
    parser.add_argument("--token", help="X-API-Key si es requerido", default=None)
    parser.add_argument("--no-synonym", action="store_true", help="No agregar como sinonimo (solo registrar sample)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload: dict[str, Any] = {
        "transcript": args.transcript,
        "intent": args.intent,
        "audio_path": args.audio,
        "add_synonym": not args.no_synonym,
    }
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-API-Key"] = args.token
    url = f"{args.base_url.rstrip('/')}/training/voice/sample"
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise SystemExit(f"Error del backend: {data}")
    print(json.dumps(data["data"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
