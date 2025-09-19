cat > run_server.sh <<'SH'
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
exec uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
SH
chmod +x run_server.sh