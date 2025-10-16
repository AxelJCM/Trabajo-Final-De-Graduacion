#!/usr/bin/env bash
set -euo pipefail

# Launch API, voice listener, and HUD on the Raspberry Pi.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/embedded"
LOG_DIR="${APP_DIR}/app/data/logs"
mkdir -p "${LOG_DIR}"

if [ -f "${APP_DIR}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "${APP_DIR}/.venv/bin/activate"
fi

export PYTHONPATH="${APP_DIR}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
HUD_MODE="${HUD_MODE:-cli}"  # cli | overlay

declare -A PIDS

start_process() {
  local name="$1"
  shift
  local log="${LOG_DIR}/${name}.log"
  echo "[run_pi_stack] starting ${name} -> $*"
  "$@" >"${log}" 2>&1 &
  PIDS["${name}"]=$!
}

start_process api uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --log-level info

wait_for_api() {
  local attempts=0
  local max_attempts="${1:-20}"
  until curl -sSf "${BASE_URL}/health" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "${attempts}" -ge "${max_attempts}" ]; then
      echo "[run_pi_stack] API did not become ready after ${attempts} attempts" >&2
      return 1
    fi
    sleep 1
  done
  echo "[run_pi_stack] API ready (after ${attempts} retries)"
}

wait_for_api || exit 1

# Voice listener (best effort; falls back gracefully if deps missing)
start_process voice python "${ROOT_DIR}/scripts/run_voice_listener.py" --base-url "${BASE_URL}"

if [ "${HUD_MODE}" == "overlay" ]; then
  start_process hud python -m app.gui.mirror_gui --overlay --base-url "${BASE_URL}"
else
  start_process hud python -m app.gui.mirror_gui --cli --base-url "${BASE_URL}"
fi

cleanup() {
  echo "[run_pi_stack] stopping services"
  for pid in "${PIDS[@]}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT

echo "[run_pi_stack] all services launched (logs in ${LOG_DIR})"
wait -n
