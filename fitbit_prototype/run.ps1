param(
    [int]$Port = 8787
)

$env:PYTHONUNBUFFERED = "1"
$env:PORT = "$Port"

uvicorn app.main:app --reload --host 0.0.0.0 --port $Port --app-dir "$PSScriptRoot"
