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
try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

from app.voice.recognizer import VoiceRecognizer, map_utterance_to_intent

try:
    import vosk  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"[VOICE] Vosk library not available: {exc}")
    sys.exit(1)

DEFAULT_RATE = 16000
DEFAULT_DEVICE = 2

# Exercise cycling state and mapping for intents
EXERCISE_CYCLE = ["squat", "pushup", "crunch"]
cycle_index = 0  # will be advanced on 'next'

INTENT_ACTIONS: Dict[str, Tuple[str, str, Optional[dict]]] = {
    # 'start' and 'next' are handled dynamically to honor cycling
    "pause": ("POST", "/session/pause", {}),
    "stop": ("POST", "/session/stop", {}),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real-time voice listener")
    # Accept index or name for --device to support stable name-based selection via env/CLI
    parser.add_argument(
        "--device",
        type=str,
        default=str(DEFAULT_DEVICE),
        help="Input device (index or exact/substr name). Example: 3 or 'USB 2.0 Camera: Audio (hw:4,0)'",
    )
    parser.add_argument(
        "--device-spec",
        type=str,
        default=None,
        help="Audio device spec: name or substring (overrides --device if provided)",
    )
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, help="Sample rate")
    parser.add_argument("--blocksize", type=int, default=8000, help="Audio block size")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--silence-window", type=float, default=1.0, help="Seconds of silence to reset recognizer")
    parser.add_argument("--dedupe-seconds", type=float, default=2.0, help="Ignore repeated intents for this window")
    parser.add_argument("--list-devices", action="store_true", help="List available audio input devices and exit")
    return parser.parse_args()


def trigger_intent(intent: str, base_url: str) -> None:
    global cycle_index
    base = base_url.rstrip("/")
    try:
        if intent == "start":
            exercise = EXERCISE_CYCLE[cycle_index]
            url = base + "/session/start"
            resp = requests.post(url, json={"exercise": exercise, "reset": True}, timeout=5)
            resp.raise_for_status()
            print(f"[VOICE] Intent 'start' executed -> {url} ({exercise})")
            return
        if intent == "next":
            cycle_index = (cycle_index + 1) % len(EXERCISE_CYCLE)
            exercise = EXERCISE_CYCLE[cycle_index]
            url = base + "/session/exercise"
            resp = requests.post(url, json={"exercise": exercise, "reset": True}, timeout=5)
            resp.raise_for_status()
            print(f"[VOICE] Intent 'next' executed -> {url} ({exercise})")
            return
        action = INTENT_ACTIONS.get(intent)
        if not action:
            print(f"[VOICE] Intent '{intent}' detected (no action configured)")
            return
        method, path, payload = action
        url = base + path
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
        if channels <= 1 or np is None:
            audio_queue.put(bytes(indata))
        else:
            try:
                buf = np.frombuffer(indata, dtype=np.int16)
                ch = channels
                n = buf.size // ch
                if n > 0:
                    buf = buf[: n * ch].reshape((n, ch)).mean(axis=1).astype(np.int16)
                    audio_queue.put(buf.tobytes())
                else:
                    audio_queue.put(bytes(indata))
            except Exception:
                audio_queue.put(bytes(indata))

    print("[VOICE] Listening... (Ctrl+C to exit)")
    # Resolve device by name or index, returning a parameter usable by sounddevice
    def resolve_device(priority_spec: Optional[str], fallback_spec: Optional[str], default_index: int) -> tuple[object, int, Optional[str]]:
        """Return (device_param, resolved_index, resolved_name).
        device_param is either an int index or an exact device name string.
        """
        def _resolve_one(spec: Optional[str]) -> Optional[tuple[object, int, Optional[str]]]:
            if spec is None:
                return None
            s = str(spec).strip()
            if not s:
                return None
            # If numeric, treat as index
            try:
                idx = int(s)
                try:
                    d = sd.query_devices(idx)
                    return idx, idx, d.get("name")
                except Exception:
                    return idx, idx, None
            except Exception:
                pass
            # Otherwise, try exact name, then substring
            try:
                devs = sd.query_devices()
                for i, d in enumerate(devs):
                    name = str(d.get("name") or "")
                    if name == s:
                        return name, i, name
                low = s.lower()
                for i, d in enumerate(devs):
                    name = str(d.get("name") or "")
                    if low in name.lower():
                        return name, i, name
            except Exception:
                return None
            return None

    # Optional: just list devices and exit (useful to compare indices inside the same process)
    if getattr(args, "list-devices", False):  # pragma: no cover
        try:
            devs = sd.query_devices()
            print("[VOICE] Lista de dispositivos de audio:")
            for i, d in enumerate(devs):
                name = d.get("name")
                max_in = int(d.get("max_input_channels") or 0)
                def_sr = d.get("default_samplerate")
                print(f"  [{i}] name='{name}' max_input_channels={max_in} default_sr={def_sr}")
        except Exception as exc:
            print(f"[VOICE] No se pudo listar dispositivos: {exc}")
        return

    # Log the provided specs for clarity
    print(f"[VOICE] Args: --device-spec={args.device_spec!r} --device={args.device!r}")

    # Prefer using the provided device name string verbatim to avoid index drift
    if args.device_spec and str(args.device_spec).strip():
        print("[VOICE] Using --device-spec; --device (index) will be ignored")
        device_param = str(args.device_spec).strip()
        # Best-effort to find its index for logging
        try:
            devs = sd.query_devices()
            idx = None
            for i, d in enumerate(devs):
                if str(d.get("name") or "") == device_param:
                    idx = i
                    resolved_name = device_param
                    break
            if idx is None:
                low = device_param.lower()
                for i, d in enumerate(devs):
                    name = str(d.get("name") or "")
                    if low in name.lower():
                        idx = i
                        resolved_name = name
                        break
            # Fuzzy pass: normalize and try token-based containment if still not found
            if idx is None:
                import re
                def norm(s: str) -> str:
                    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
                spec_norm = norm(device_param)
                spec_tokens = [t for t in spec_norm.split() if t]
                for i, d in enumerate(devs):
                    name = str(d.get("name") or "")
                    cand = norm(name)
                    if spec_norm and spec_norm in cand:
                        idx = i
                        resolved_name = name
                        break
                    # Require at least 2 token matches for a fuzzy hit
                    matches = sum(1 for t in spec_tokens if t in cand)
                    if len(spec_tokens) >= 3 and matches >= 2:
                        idx = i
                        resolved_name = name
                        break
            resolved_index = idx if idx is not None else -1
            if idx is None:
                resolved_name = device_param
        except Exception:
            resolved_index = -1
            resolved_name = device_param
    else:
        # No name provided; resolve from --device (could be index or name)
        res = None
        for spec in (args.device,):
            res = resolve_device(spec, None, DEFAULT_DEVICE)
            if res is not None:
                break
        if res is None:
            try:
                d = sd.query_devices(DEFAULT_DEVICE)
                device_param, resolved_index, resolved_name = DEFAULT_DEVICE, DEFAULT_DEVICE, d.get("name")
            except Exception:
                device_param, resolved_index, resolved_name = DEFAULT_DEVICE, DEFAULT_DEVICE, None
        else:
            device_param, resolved_index, resolved_name = res

    # Log selected device info; do not auto-switch
    try:
        # If we have an index, query details; otherwise log the provided name and dump device list to aid debugging
        if isinstance(resolved_index, int) and resolved_index >= 0:
            dinfo = sd.query_devices(resolved_index)
            name = dinfo.get("name")
            max_in = int(dinfo.get("max_input_channels") or 0)
            def_sr = dinfo.get("default_samplerate")
            print(f"[VOICE] Device resuelto: index={resolved_index} name='{name}' max_input_channels={max_in} default_sr={def_sr}")
        else:
            name = str(device_param)
            max_in = -1
            def_sr = None
            print(f"[VOICE] Device resuelto por nombre: name='{name}' (index desconocido)")
            # List devices to help find proper substring
            try:
                devs = sd.query_devices()
                print("[VOICE] Dispositivos disponibles en este proceso:")
                for i, d in enumerate(devs):
                    nm = d.get("name")
                    mi = int(d.get("max_input_channels") or 0)
                    dsr = d.get("default_samplerate")
                    print(f"  [{i}] name='{nm}' max_input_channels={mi} default_sr={dsr}")
            except Exception:
                pass
        # If device supports stereo input, capture both and downmix to mono for Vosk
        if isinstance(max_in, int) and max_in >= 2:
            channels = 2
    except Exception as exc:
        print(f"[VOICE] No se pudo consultar dispositivos (se usara device={device_param!r}): {exc}")

    # Try opening stream; fallback to device default samplerate when needed
    stream = None
    try:
        stream = sd.RawInputStream(
            samplerate=args.rate,
            blocksize=args.blocksize,
            device=device_param,
            dtype="int16",
            channels=channels,
            callback=audio_callback,
        )
        stream.start()
    except Exception as exc1:
        try:
            d = sd.query_devices(resolved_index if isinstance(resolved_index, int) and resolved_index >= 0 else device_param)
            name = d.get("name")
            def_sr = int(float(d.get("default_samplerate") or args.rate))
        except Exception:
            def_sr = args.rate
        if def_sr != args.rate:
            try:
                print(f"[VOICE] Reintentando con sample_rate={def_sr} (device={args.device}, resolved_index={resolved_index}, name={name!r})")
                stream = sd.RawInputStream(
                    samplerate=def_sr,
                    blocksize=args.blocksize,
                    device=device_param,
                    dtype="int16",
                    channels=channels,
                    callback=audio_callback,
                )
                stream.start()
                rec = vosk.KaldiRecognizer(vosk_model, def_sr)
            except Exception as exc2:
                # Try channels=2
                try:
                    print(f"[VOICE] Reintentando con channels=2 y sample_rate={def_sr} (device={args.device}, resolved_index={resolved_index}, name={name!r})")
                    stream = sd.RawInputStream(
                        samplerate=def_sr,
                        blocksize=args.blocksize,
                        device=device_param,
                        dtype="int16",
                        channels=2,
                        callback=audio_callback,
                    )
                    stream.start()
                    channels = 2
                    rec = vosk.KaldiRecognizer(vosk_model, def_sr)
                except Exception as exc3:
                    raise SystemExit(
                        f"[VOICE] Could not open audio input (device_arg={args.device!r}, device_spec={args.device_spec!r}, resolved_index={resolved_index}, name={name!r}, device_param={device_param!r}): {exc1} | fallback_sr={def_sr} -> {exc2} | fallback_channels=2 -> {exc3}"
                    ) from exc3
        else:
            # Try channels=2 with original sample rate
            try:
                print(f"[VOICE] Reintentando con channels=2 (device={args.device}, resolved_index={resolved_index})")
                stream = sd.RawInputStream(
                    samplerate=args.rate,
                    blocksize=args.blocksize,
                    device=device_param,
                    dtype="int16",
                    channels=2,
                    callback=audio_callback,
                )
                stream.start()
                channels = 2
            except Exception as exc2:
                raise SystemExit(
                    f"[VOICE] Could not open audio input (device_arg={args.device!r}, device_spec={args.device_spec!r}, resolved_index={resolved_index}, device_param={device_param!r}): {exc1} | channels=2 -> {exc2}"
                ) from exc2

    try:
        # Do not force periodic resets; let Vosk decide utterance boundaries
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
            else:
                # Optional: print partials for debugging
                # pr = json.loads(rec.PartialResult())
                # if pr.get('partial'):
                #     print(f"[VOICE] Partial: {pr['partial']}")
                pass
    finally:
        if stream is not None:
            stream.stop()
            stream.close()


if __name__ == "__main__":
    main()
