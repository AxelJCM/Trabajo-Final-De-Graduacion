from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "training"
POSE_DIR = BASE_DIR / "pose"
VOICE_DIR = BASE_DIR / "voice"
COMMANDS_FILE = Path(__file__).resolve().parent.parent / "data" / "voice_commands.json"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def save_pose_sample(label: str, joints: List[Dict[str, Any]], angles: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Path:
    """Persist a labeled pose sample for future training."""
    _ensure_dir(POSE_DIR)
    slug = label.lower().replace(" ", "_")
    fname = f"{_timestamp()}_{slug}.json"
    path = POSE_DIR / fname
    payload = {
        "label": label,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "joints": joints,
        "angles": angles,
        "metadata": metadata or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved pose training sample to {}", path)
    return path


def save_voice_sample(transcript: str, intent: str, audio_path: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Path:
    """Persist a voice sample descriptor for training datasets."""
    _ensure_dir(VOICE_DIR)
    slug = intent.lower().replace(" ", "_")
    fname = f"{_timestamp()}_{slug}.json"
    path = VOICE_DIR / fname
    payload = {
        "transcript": transcript.strip(),
        "intent": intent,
        "audio_path": audio_path,
        "metadata": metadata or {},
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved voice training sample to {}", path)
    return path


def load_voice_commands() -> Dict[str, str]:
    if COMMANDS_FILE.exists():
        try:
            return json.loads(COMMANDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read voice commands dataset {}", COMMANDS_FILE)
            return {}
    return {}


def save_voice_commands(mapping: Dict[str, str]) -> None:
    _ensure_dir(COMMANDS_FILE.parent)
    COMMANDS_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Updated voice commands dataset {}", COMMANDS_FILE)


def register_voice_synonym(utterance: str, intent: str) -> None:
    """Persist a new utterance->intent mapping."""
    utterance = utterance.strip().lower()
    mapping = load_voice_commands()
    mapping[utterance] = intent
    save_voice_commands(mapping)
