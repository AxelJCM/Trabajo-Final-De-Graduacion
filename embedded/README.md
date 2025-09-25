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
- POST /config
- POST /voice/test

All responses use { success, data, error }.

## CLI fallback
If GUI isn't available, run:

```powershell
python -m app.gui.mirror_gui --cli --base-url http://127.0.0.1:8000
```
