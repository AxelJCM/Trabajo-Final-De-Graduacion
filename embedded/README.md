# Embedded Backend (FastAPI + Python)

Provides the Smart Mirror backend running on Raspberry Pi 4.

- Vision (OpenCV + MediaPipe)
- Biometrics (Fitbit Web API)
- Voice (Vosk/Google)
- GUI (PyQt5 or Tkinter)

## Run locally

1. Create venv and install deps
2. Start server

Try it (PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r embedded/requirements.txt; uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints
- GET /health
- POST /posture
- POST /biometrics
- GET /biometrics/last
- POST /config
- POST /voice/test
- POST /training/pose/sample
- POST /training/voice/sample

All responses use { success, data, error }.

## Training data collection
- Capture pose sample: `python scripts/collect_pose_sample.py sentadilla --notes "buen angulo"`
- Registrar sinónimo de voz: `python scripts/add_voice_synonym.py "inicia cardio" start_routine`
- Grabar y registrar frase (audio + sinónimo): `python scripts/record_and_register_voice.py "inicia rutina" start_routine --output embedded/app/data/training/voice`
- Entrenar clasificador de intents (requiere scikit-learn): `python scripts/train_voice_intent.py`

Pose samples se guardan en `embedded/app/data/training/pose/`, mientras que voz en `embedded/app/data/training/voice/`. Configura `USE_VOSK_OFFLINE=1` y `VOSK_MODEL_PATH` en `.env` después de descargar un modelo adecuado (por ejemplo `vosk-model-small-es-0.42`). Si entrenas un clasificador personalizado, apunta `VOICE_INTENT_MODEL_PATH` al archivo `.joblib` generado para habilitar el fallback inteligente.

## CLI fallback
If GUI isn't available, run:

```powershell
python -m app.gui.mirror_gui --cli --base-url http://127.0.0.1:8000
```
