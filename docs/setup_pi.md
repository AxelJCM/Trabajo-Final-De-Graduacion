# Raspberry Pi setup (device-less MVP)

Prereqs: Raspberry Pi OS Lite, Python 3.10+, network.

Steps:
- Clone repo to ~/smart-mirror
- python -m venv .venv; source .venv/bin/activate
- pip install -r embedded/requirements.txt (you can skip heavy deps like mediapipe if space limited)
- Copy .env.example to .env and set EXPOSED_ORIGINS and optional API_KEY
- Run server: python embedded/run_server.py

Test endpoints:
- GET http://<pi>:8000/health
- POST http://<pi>:8000/biometrics {}
- POST http://<pi>:8000/posture {}

CLI mirror (no GUI):
- python -m app.gui.mirror_gui --cli --base-url http://<pi>:8000

Notes:
- SQLite DB created at embedded/app/data/smartmirror.db
- To persist config via POST /config include header X-API-Key when API_KEY is set.
