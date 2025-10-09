from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at_utc: datetime
    scope: Optional[str] = None
    token_type: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_tokens() -> Optional[Tokens]:
    if not TOKENS_PATH.exists():
        return None
    try:
        data = json.loads(TOKENS_PATH.read_text())
        return Tokens(
            access_token=data.get("access_token",""),
            refresh_token=data.get("refresh_token",""),
            expires_at_utc=datetime.fromisoformat(data.get("expires_at_utc")),
            scope=data.get("scope"),
            token_type=data.get("token_type"),
        )
    except Exception:
        return None


def save_tokens(access_token: str, refresh_token: str, expires_in: int, scope: str | None, token_type: str | None) -> Tokens:
    expires_at = _now() + timedelta(seconds=int(expires_in or 3600))
    t = Tokens(access_token=access_token, refresh_token=refresh_token, expires_at_utc=expires_at, scope=scope, token_type=token_type)
    TOKENS_PATH.write_text(json.dumps({
        "access_token": t.access_token,
        "refresh_token": t.refresh_token,
        "expires_at_utc": t.expires_at_utc.isoformat(),
        "scope": t.scope,
        "token_type": t.token_type,
    }))
    return t
