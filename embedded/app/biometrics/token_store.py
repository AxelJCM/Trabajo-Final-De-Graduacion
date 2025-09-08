"""Token store for Fitbit OAuth2 tokens using a JSON file.

Not secure for production; for prototype only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional


DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "tokens.json")


@dataclass
class FitbitTokens:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 28800


class TokenStore:
    """Tiny file-based token store."""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path

    def save(self, tokens: FitbitTokens) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(asdict(tokens), f)

    def load(self) -> Optional[FitbitTokens]:
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return FitbitTokens(**data)
        except Exception:
            return None
