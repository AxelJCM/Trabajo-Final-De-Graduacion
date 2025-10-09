# Fitbit Prototype (Standalone)

Pequeño servicio FastAPI independiente para probar y validar la integración con la Fitbit Web API (OAuth2 + métricas), aislado del proyecto principal. Úsalo para obtener tokens y leer HR/steps; luego se integrará al TFG.

## Requisitos
- Python 3.10+
- Una app registrada en https://dev.fitbit.com/apps
  - Scopes: heartrate profile activity
  - Redirect URI: http://localhost:8787/auth/fitbit/callback (o ajusta el puerto según tu ejecución)

## Configuración (Windows PowerShell)
```powershell
# En la raíz del repo o dentro de fitbit_prototype
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r fitbit_prototype\requirements.txt
Copy-Item fitbit_prototype\.env.example fitbit_prototype\.env
# Edita fitbit_prototype/.env y coloca tus credenciales
```

Variables .env:
- FITBIT_CLIENT_ID=...
- FITBIT_CLIENT_SECRET=... (opcional; si se omite, se usará PKCE)
- FITBIT_REDIRECT_URI=http://localhost:8787/auth/fitbit/callback
- PORT=8787

## Ejecutar
```powershell
# Dentro del venv
powershell -ExecutionPolicy Bypass -File fitbit_prototype\run.ps1
```

Luego abre:
- http://localhost:8787/view → botón “Connect Fitbit”
- http://localhost:8787/fitbit/status → estado de conexión
- http://localhost:8787/fitbit/last → HR y pasos (si hay tokens válidos)

## Endpoints
- GET /health
- GET /auth/fitbit/login
- GET /auth/fitbit/callback
- POST /fitbit/refresh
- GET /fitbit/status
- GET /fitbit/last
- GET /view (página simple de prueba)

## Notas
- Los tokens se guardan en `fitbit_prototype/tokens.json` (no subas tus secretos).
- En producción del TFG se migrará a SQLite/SQLAlchemy; aquí se prioriza simplicidad.