cat > run_server.sh <<'SH'
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Performance-friendly defaults for Raspberry Pi
export MODEL_COMPLEXITY=${MODEL_COMPLEXITY:-0}
export CAMERA_WIDTH=${CAMERA_WIDTH:-640}
export CAMERA_HEIGHT=${CAMERA_HEIGHT:-360}
export CAMERA_FPS=${CAMERA_FPS:-15}
# Uncomment to force mock vision (no camera/mediapipe init)
# export VISION_MOCK=1

source .venv/bin/activate
exec uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
SH
chmod +x run_server.sh