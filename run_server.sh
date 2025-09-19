cat > run_server.sh <<'SH'
#!/usr/bin/env bash
set -e

# Move to repo root, then into embedded backend folder
cd "$(dirname "$0")"
cd embedded

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

# Activate the embedded venv
if [ -f .venv/bin/activate ]; then
	source .venv/bin/activate
else
	echo "Virtual env not found at embedded/.venv. Create it and install requirements first." >&2
	echo "python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
	exit 1
fi

exec uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
SH
chmod +x run_server.sh