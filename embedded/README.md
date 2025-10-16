# Embedded Backend (FastAPI + Python)

Servicio que corre en la Raspberry Pi y orquesta visión, biometría, HUD y voz para el TFG.

## Puesta en marcha rápida (PC de desarrollo)
1. `python -m venv .venv`
2. Activar el entorno y `pip install -r embedded/requirements.txt`
3. `uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000`

## Stack completo en la Pi
1. Configura `embedded/.env` (ver `.env.example`).
2. En la Pi ejecuta:
   ```bash
   ./scripts/run_pi_stack.sh
   ```
   - Variables opcionales: `BASE_URL` (por defecto `http://127.0.0.1:8000`) y `HUD_MODE=overlay|cli`.
3. El script levanta:
   - API FastAPI (`uvicorn`)
   - Listener de voz (`scripts/run_voice_listener.py`)
   - HUD (CLI o PyQt overlay)
   - Logs en `embedded/app/data/logs/`.

Detén todo con `Ctrl+C` (el script hace cleanup de procesos).

## HUD / CLI
- Esquina sup. izquierda: estado de sesión (Activa/Pausa/Finalizada), hora de inicio y último comando con marca temporal.
- Esquina sup. derecha: frecuencia cardíaca con color según zona (cálculo Karvonen), pasos y estado Fitbit (`🟢/🟡/🔴`).
- Centro izquierdo: ejercicio actual, reps totales, reps del ejercicio, fase del movimiento y calidad instantánea.
- Barra inferior: tiempo activo + notificación de errores.

CLI equivalente:
```bash
python -m app.gui.mirror_gui --cli --base-url http://127.0.0.1:8000
```

## Endpoints principales
- `GET /health`
- `POST /posture` → FPS, latencias p50/p95, rep_totals, fase y feedback granular.
- `POST /biometrics` / `GET /biometrics/last` → FC, pasos, zona (`zone_color`), estado Fitbit y `staleness_sec`.
- `POST /session/start|pause|stop|exercise` → control de sesión.
- `GET /session/status` → datos vivos: `status`, `last_command`, `duration_active_sec`, `rep_totals`, `feedback`.
- `GET /session/last` y `GET /session/history?limit=N` → histórico persistido en SQLite con `avg_hr`, `max_hr`, `total_reps`, `avg_quality`.

Todas las respuestas siguen la forma `{ "success": bool, "data": ..., "error": str|None }`.

## Configuración de visión y repeticiones
Variables en `.env.example` permiten ajustar cámara y umbrales por ejercicio:
```
CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, MODEL_COMPLEXITY
VISION_MOCK, POSE_LATENCY_WINDOW, POSE_QUALITY_WINDOW
SQUAT_DOWN_ANGLE / SQUAT_UP_ANGLE
PUSHUP_DOWN_ANGLE / PUSHUP_UP_ANGLE
CRUNCH_DOWN_ANGLE / CRUNCH_UP_ANGLE
```
`PoseEstimator` expone `reset_session()` y `get_average_quality()` para métricas por sesión.

## Biometría y almacenamiento
- Tokens Fitbit en `smartmirror.db`.
- Métricas recientes se guardan en `biometric_sample` (FC, pasos, `zone_name`, `fitbit_status`, etc.).
- Zona cardíaca coloreada usando fórmula de Karvonen (`HR_RESTING`, `HR_MAX`).
- Estado Fitbit (`fitbit_status_level`) cambia a amarillo/rojo si los datos están caducos o hay error.

## Control por voz
- Listener (`scripts/run_voice_listener.py`) usa Vosk + clasificadores entrenables (`app/voice/recognizer.py`).
- Intents soportados: `start`, `start_routine`, `pause`, `stop`, `next`.
  - `start/start_routine` → `/session/start` (ciclo comienza en sentadilla).
  - `pause` → `/session/pause`
  - `stop` → `/session/stop`
  - `next` → rota entre `squat`, `pushup`, `crunch` (`/session/exercise`).
- `last_command` y hora de ejecución aparecen en el HUD al instante.

### Entrenamiento y registro de voz
- Añadir sinónimo: `python scripts/add_voice_synonym.py "inicia cardio" start_routine`
- Grabación etiquetada: `python scripts/record_and_register_voice.py "inicia rutina" start_routine`
- Re-entrenar: `python scripts/train_voice_intent.py`
- Listener standalone: `python scripts/run_voice_listener.py --base-url http://127.0.0.1:8000`

## Métricas y validación
- **Conteo de repeticiones:** objetivo ≤ 1 error cada 10 reps. Validar por ejercicio observando `rep_totals` vs conteo manual.
- **Latencia visión:** revisar `latency_ms_p50` / `latency_ms_p95` (en `POST /posture` y logs). Meta \< 120 ms p50.
- **FPS pipeline:** campo `fps` en `POST /posture` (esperado 12–15 FPS en la Pi).
- **Biometría:** `staleness_sec` debe permanecer \< `FITBIT_POLL_INTERVAL * 2` cuando Fitbit está sincronizado.
- **Voz:** registrar tasa de aciertos con `scripts/run_voice_listener.py --verbose` y comparar contra `last_command` en el HUD.
Documenta los resultados en `docs` o en tu bitácora de capítulos según corresponda.
