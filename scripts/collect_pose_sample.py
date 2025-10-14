#!/usr/bin/env python3
"""Capture a labeled pose sample via the training API."""
from __future__ import annotations

import argparse
import json
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a labeled pose sample")
    parser.add_argument("label", help="Nombre de la clase del sample")
    parser.add_argument("--notes", help="Notas opcionales", default=None)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="URL del backend (default: %(default)s)")
    parser.add_argument("--token", help="X-API-Key si es requerido", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload: dict[str, Any] = {"label": args.label, "notes": args.notes}
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-API-Key"] = args.token
    url = f"{args.base_url.rstrip('/')}/training/pose/sample"
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise SystemExit(f"Error del backend: {data}")
    print(json.dumps(data["data"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
