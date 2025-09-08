"""Virtual trainer engine.

Generates JSON routines and adapts based on posture feedback and heart rate.
"""
from __future__ import annotations

import uuid
from typing import Optional

from loguru import logger

from app.api.schemas import RoutineOutput


class TrainerEngine:
    """Produces and adapts training routines."""

    def generate_routine(self, user_id: str, performance: Optional[dict]) -> RoutineOutput:
        """Return a basic routine, adjusting intensity if performance given."""
        base_blocks = [
            {"type": "warmup", "name": "Jumping Jacks", "reps": 30},
            {"type": "strength", "name": "Push Ups", "reps": 12},
            {"type": "core", "name": "Plank", "secs": 45},
            {"type": "cooldown", "name": "Stretch", "secs": 60},
        ]
        duration = 15
        if performance:
            hr = performance.get("heart_rate_bpm", 0)
            if hr > 130:
                # reduce intensity
                for b in base_blocks:
                    if "reps" in b:
                        b["reps"] = max(8, int(b["reps"] * 0.8))
                duration = 12
            elif hr < 90:
                for b in base_blocks:
                    if "reps" in b:
                        b["reps"] = int(b["reps"] * 1.2)
                duration = 18
        rid = str(uuid.uuid4())
        logger.info("generated routine {} for user {}", rid, user_id)
        return RoutineOutput(routine_id=rid, blocks=base_blocks, duration_min=duration)
