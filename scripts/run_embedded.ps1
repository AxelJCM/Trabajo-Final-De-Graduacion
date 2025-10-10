# Runs the embedded FastAPI server loading environment variables from embedded/.env
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_embedded.ps1

param(
    [int]$PortOverride = 0
)

$ErrorActionPreference = 'Stop'

# Compute repo root and paths
$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot "embedded\.env"
$venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"

# Load .env if present
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name = $Matches[1]
            $val = $Matches[2]
            # Strip surrounding quotes
            $val = $val.Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($name, $val)
        }
    }
}

# Determine port
$port = $PortOverride
if (-not $port) {
    $apiPort = [Environment]::GetEnvironmentVariable('API_PORT')
    if ($apiPort) { $port = [int]$apiPort }
}
if (-not $port) { $port = 8000 }

$env:PYTHONUNBUFFERED = "1"

# Run server using repo-local venv if available
$uvicornArgs = @('app.api.main:app', '--reload', '--host', '0.0.0.0', '--port', $port, '--app-dir', 'embedded')

if (Test-Path $venvPy) {
    & $venvPy -m uvicorn @uvicornArgs
} else {
    # Fallback to global uvicorn
    uvicorn @uvicornArgs
}
