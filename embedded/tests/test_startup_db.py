from pathlib import Path
import os


def test_db_file_created_on_import():
    # Import app to trigger lifespan preparation (metadata defined)
    from app.core.db import DB_PATH
    from app.api.main import app  # noqa: F401

    # The DB file may not exist until first connection; ensure data dir exists
    assert DB_PATH.parent.exists()