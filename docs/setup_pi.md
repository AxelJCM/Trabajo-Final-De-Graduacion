# Raspberry Pi setup (device-less and live hardware)

Prereqs: Raspberry Pi OS (Bookworm), Python 3.10+, network.

Steps:
- Clone repo to ~/smart-mirror
- python -m venv .venv; source .venv/bin/activate
- sudo apt-get update && sudo apt-get install -y libatlas-base-dev libcap-dev v4l-utils
- pip install -r embedded/requirements.txt
- Copy embedded/.env.example to embedded/.env and set FITBIT_* and camera settings
- For camera, verify device: `v4l2-ctl --list-devices` and `ls -l /dev/video*`; set CAMERA_INDEX accordingly.
- For performance on Pi 4: `CAMERA_WIDTH=640`, `CAMERA_HEIGHT=480`, `CAMERA_FPS=30`, `MODEL_COMPLEXITY=0`.
- Run server: `python embedded/run_server.py`

Fitbit OAuth:
- Create a Fitbit app at dev.fitbit.com. Scopes: `heartrate profile activity`.
- Set redirect URI: `http://<pi_ip>:8000/auth/fitbit/callback`.
- Update `.env` FITBIT_CLIENT_ID, FITBIT_CLIENT_SECRET, FITBIT_REDIRECT_URI.
- Start server, open `http://<pi_ip>:8000/auth/fitbit/login` and complete consent.
- Without the optional *Intraday Data* approval Fitbit only returns daily summaries (resting heart rate). Request Intraday access in the Fitbit developer portal if you need per-minute/second samples.
- Open the Fitbit mobile app to force a sync, then call `/biometrics` or `/biometrics/last`.

Testing endpoints:
- GET http://<pi_ip>:8000/health
- POST http://<pi_ip>:8000/biometrics {}
- GET http://<pi_ip>:8000/biometrics/last
- POST http://<pi_ip>:8000/posture {}

Mirror display:
- CLI: `python -m app.gui.mirror_gui --cli --base-url http://<pi_ip>:8000`
- Overlay (if PyQt5 installed): `python -m app.gui.mirror_gui --overlay --base-url http://<pi_ip>:8000`

Notes:
- SQLite DB created at embedded/app/data/smartmirror.db
- To persist config via POST /config include header `X-API-Key` when API_KEY is set.
