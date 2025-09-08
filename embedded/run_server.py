"""Run the FastAPI server (dev helper)."""
from __future__ import annotations

import uvicorn

from app.core.config import get_settings
from app.core.logging_config import setup_logging


def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    uvicorn.run("app.api.main:app", host=s.api_host, port=s.api_port, reload=True)


if __name__ == "__main__":
    main()
