#!/usr/bin/env bash
# Setup script for Raspberry Pi (Raspbian) to install dependencies.
# Usage: bash embedded/setup.sh

set -euo pipefail

echo "[setup] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv libatlas-base-dev libportaudio2 libasound2-dev

# Create venv
if [ ! -d "venv" ]; then
  echo "[setup] Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

pip install --upgrade pip

echo "[setup] Installing Python requirements..."
pip install -r embedded/requirements.txt

# Optional: enable camera and audio (manual on first time)
echo "[setup] NOTE: Ensure camera is enabled via raspi-config and verify microphone works."

echo "[setup] Done. To run API: source venv/bin/activate && uvicorn app.api.main:app --host 0.0.0.0 --port 8000"
