#!/usr/bin/env bash
set -euo pipefail

# Move to repo root, then into embedded backend folder
cd "$(dirname "$0")/embedded"

# Load .env if present
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Performance-friendly defaults for Raspberry Pi
export MODEL_COMPLEXITY=${MODEL_COMPLEXITY:-0}
export CAMERA_WIDTH=${CAMERA_WIDTH:-640}
export CAMERA_HEIGHT=${CAMERA_HEIGHT:-360}
export CAMERA_FPS=${CAMERA_FPS:-15}
export CAMERA_INDEX=${CAMERA_INDEX:-0}
# Uncomment to force mock vision (no camera/mediapipe init)
# export VISION_MOCK=1
# Ensure mock is disabled by default
unset VISION_MOCK || true

# Activate the embedded venv (create if missing)
if [ ! -f .venv/bin/activate ]; then
  echo "Creating virtual environment in embedded/.venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# Install requirements if needed
pip install -r requirements.txt

# Diagnostics to help verify env was loaded
echo "[run_server] API_HOST=${API_HOST:-unset} API_PORT=${API_PORT:-unset}"
if [ -n "${FITBIT_CLIENT_ID:-}" ]; then
  echo "[run_server] FITBIT_CLIENT_ID is set."
else
  echo "[run_server] WARNING: FITBIT_CLIENT_ID is NOT set. Fitbit login will show 'setup required'." >&2
fi

# Run without --reload on Raspberry Pi to avoid duplicate camera in reloader
exec uvicorn app.api.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"