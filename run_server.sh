#!/usr/bin/env bash
set -euo pipefail

# Move to repo root, then into embedded backend folder
cd "$(dirname "$0")/embedded"

# Load .env if present (robust to CRLF and BOM, no 'source' to avoid syntax errors)
if [ -f .env ]; then
  echo "[run_server] Loading embedded/.env"
  i=0
  while IFS= read -r line || [ -n "$line" ]; do
    i=$((i+1))
    # strip CR (Windows line endings)
    line=${line%$'\r'}
    # strip UTF-8 BOM on first line if present
    if [ $i -eq 1 ] && printf '%s' "$line" | head -c 3 | grep -q "$(printf '\xEF\xBB\xBF')"; then
      line=$(printf '%s' "$line" | sed '1s/^\xEF\xBB\xBF//')
    fi
    # skip blanks/comments
    case "$line" in
      ''|\#*) continue ;;
    esac
    # only export KEY=VALUE lines with a valid variable name
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      export "$line"
    else
      echo "[run_server] Skipping invalid line $i in .env: $line" >&2
    fi
  done < .env
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
if [ -n "${FITBIT_CLIENT_SECRET:-}" ]; then
  echo "[run_server] FITBIT_CLIENT_SECRET is set."
else
  echo "[run_server] WARNING: FITBIT_CLIENT_SECRET is NOT set. Token exchange will fail with 401 invalid_client." >&2
fi
if [ -n "${FITBIT_REDIRECT_URI:-}" ]; then
  echo "[run_server] FITBIT_REDIRECT_URI=${FITBIT_REDIRECT_URI}"
fi

# Run without --reload on Raspberry Pi to avoid duplicate camera in reloader
exec uvicorn app.api.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"