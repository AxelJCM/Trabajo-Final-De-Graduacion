#!/usr/bin/env bash
# Setup script for Raspberry Pi (Raspbian) to install dependencies.
# Usage: bash embedded/setup.sh (run from repo root)

set -euo pipefail

echo "[setup] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv libatlas-base-dev libportaudio2 libasound2-dev

# Move into embedded folder to keep venv local to the backend
cd "$(dirname "$0")"

# Create venv (embedded/.venv) compatible with run_server.sh
if [ ! -d ".venv" ]; then
  echo "[setup] Creating virtual environment in embedded/.venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip

echo "[setup] Installing Python requirements..."
pip install -r requirements.txt

# Optional: enable camera and audio (manual on first time)
echo "[setup] NOTE: Enable camera via raspi-config/libcamera, verify microphone, and ensure Internet/DNS works."

echo "[setup] Done. To run API: cd embedded && source .venv/bin/activate && ../run_server.sh"
