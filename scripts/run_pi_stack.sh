#!/usr/bin/env bash
set -euo pipefail

# Launch API, voice listener, and HUD on the Raspberry Pi.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/embedded"
LOG_DIR="${APP_DIR}/app/data/logs"
mkdir -p "${LOG_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d "${APP_DIR}/.venv" ]; then
  echo "[run_pi_stack] creating virtualenv at ${APP_DIR}/.venv"
  "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv" --system-site-packages
  CREATED_VENV=1
else
  CREATED_VENV=0
fi

if [ -f "${APP_DIR}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "${APP_DIR}/.venv/bin/activate"
fi

if [ "${CREATED_VENV}" -eq 1 ] || [ ! -f "${APP_DIR}/.venv/.deps_installed" ] || [ "${FORCE_PIP_INSTALL:-0}" = "1" ]; then
  echo "[run_pi_stack] installing Python dependencies (this may take a minute)"
  python -m pip install --upgrade pip >/dev/null 2>&1 || true
  python -m pip install -r "${APP_DIR}/requirements.txt"
  touch "${APP_DIR}/.venv/.deps_installed"
fi

if [ -f "${APP_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${APP_DIR}/.env"
  set +a
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
LISTENER_ARGS=("${ROOT_DIR}/scripts/run_voice_listener.py" "--base-url" "${BASE_URL}")
if [ -n "${VOICE_LISTENER_DEVICE:-}" ]; then
  if [[ "${VOICE_LISTENER_DEVICE}" =~ ^[0-9]+$ ]]; then
    # Numeric -> pass as --device (index), to mimic vosk_check behavior exactly
    LISTENER_ARGS+=("--device" "${VOICE_LISTENER_DEVICE}")
  else
    # String -> pass as --device-spec (name or substring)
    LISTENER_ARGS+=("--device-spec" "${VOICE_LISTENER_DEVICE}")
  fi
fi
if [ -n "${VOICE_LISTENER_RATE:-}" ]; then
  LISTENER_ARGS+=("--rate" "${VOICE_LISTENER_RATE}")
fi
if [ -n "${VOICE_LISTENER_BLOCKSIZE:-}" ]; then
  LISTENER_ARGS+=("--blocksize" "${VOICE_LISTENER_BLOCKSIZE}")
fi
if [ -n "${VOICE_LISTENER_SILENCE_WINDOW:-}" ]; then
  LISTENER_ARGS+=("--silence-window" "${VOICE_LISTENER_SILENCE_WINDOW}")
fi
if [ -n "${VOICE_LISTENER_DEDUPE_SECONDS:-}" ]; then
  LISTENER_ARGS+=("--dedupe-seconds" "${VOICE_LISTENER_DEDUPE_SECONDS}")
fi
start_process voice "${APP_DIR}/.venv/bin/python" "${LISTENER_ARGS[@]}"

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
